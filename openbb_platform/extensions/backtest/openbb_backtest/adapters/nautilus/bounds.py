"""Process bounds for the worker (#1355 T03): memory limit and process-tree kill.

Windows: a Job Object (``ctypes``) with a job-wide committed-memory limit and
kill-on-close; :meth:`ProcessBounds.kill_tree` terminates every process in the
job, including grandchildren. POSIX: a new session (process group) and
``RLIMIT_AS``; the tree kill signals the group. The container runtime uses
``docker run --memory`` instead.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
from ctypes import wintypes
from typing import Any

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_LIMIT_JOB_MEMORY = 0x200
_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_CREATE_SUSPENDED = 0x00000004
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_RESUME_FAILED = 0xFFFFFFFF


class _BasicLimits(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimits(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


def _kernel32() -> Any:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.TerminateJobObject.restype = wintypes.BOOL
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Thread32First.restype = wintypes.BOOL
    k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
    k32.Thread32Next.restype = wintypes.BOOL
    k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
    k32.OpenThread.restype = wintypes.HANDLE
    k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.ResumeThread.restype = wintypes.DWORD  # 0xFFFFFFFF on failure
    k32.ResumeThread.argtypes = [wintypes.HANDLE]
    return k32


def _os_error(what: str) -> OSError:
    return OSError(ctypes.get_last_error(), f"{what} failed")  # type: ignore[attr-defined]


class ProcessBounds:
    """Memory limit + tree kill for one worker process."""

    def __init__(self, memory_bytes: int | None = None):
        self._memory = memory_bytes
        self._job: Any = None
        self._k32: Any = None
        self._suspended = False
        if os.name == "nt":
            self._k32 = _kernel32()
            job = self._k32.CreateJobObjectW(None, None)
            if not job:
                raise _os_error("CreateJobObjectW")
            self._job = job
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = _LIMIT_KILL_ON_JOB_CLOSE
            if memory_bytes:
                info.BasicLimitInformation.LimitFlags |= _LIMIT_JOB_MEMORY
                info.JobMemoryLimit = memory_bytes
            if not self._k32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                self.close()
                raise _os_error("SetInformationJobObject")

    def popen_kwargs(self) -> dict[str, Any]:
        """Extra ``Popen`` arguments.

        Windows: ``CREATE_SUSPENDED``, so the child runs no code until
        :meth:`attach` has put it in the job. POSIX: own process group +
        ``RLIMIT_AS``.
        """
        if os.name == "nt":
            self._suspended = True
            return {"creationflags": _CREATE_SUSPENDED}
        memory = self._memory

        def limit() -> None:  # pragma: no cover - runs in the POSIX child
            if memory:
                import resource  # pylint: disable=import-outside-toplevel

                resource.setrlimit(resource.RLIMIT_AS, (memory, memory))  # type: ignore[attr-defined]

        return {"start_new_session": True, "preexec_fn": limit}

    def attach(self, proc: subprocess.Popen) -> None:
        """Put ``proc`` (and its future children) into the job, then let it run.

        A child started with :meth:`popen_kwargs` is suspended until it is in the
        job. If assignment or resume fails the job is terminated (killing the
        still-suspended child) and the error is raised.
        """
        if self._job is None:
            return
        handle = int(proc._handle)  # type: ignore[attr-defined]  # pylint: disable=protected-access
        try:
            if not self._k32.AssignProcessToJobObject(self._job, handle):
                raise _os_error("AssignProcessToJobObject")
            if self._suspended:
                self._resume_main_thread(proc.pid)
        except OSError:
            self._k32.TerminateJobObject(self._job, 1)
            raise

    def _resume_main_thread(self, pid: int) -> None:
        """Resume the (only) thread of the suspended process ``pid``."""
        k32 = self._k32
        snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
        if snap in (None, ctypes.c_void_p(-1).value):
            raise _os_error("CreateToolhelp32Snapshot")
        try:
            entry = _ThreadEntry()
            # pylint: disable-next=invalid-name,attribute-defined-outside-init
            entry.dwSize = ctypes.sizeof(entry)
            more = k32.Thread32First(snap, ctypes.byref(entry))
            while more:
                if entry.th32OwnerProcessID == pid:
                    self._resume_thread(entry.th32ThreadID)
                    return
                more = k32.Thread32Next(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        raise OSError(0, "no thread found for the suspended worker")

    def _resume_thread(self, thread_id: int) -> None:
        k32 = self._k32
        thread = k32.OpenThread(_THREAD_SUSPEND_RESUME, False, thread_id)
        if not thread:
            raise _os_error("OpenThread")
        try:
            if k32.ResumeThread(thread) == _RESUME_FAILED:
                raise _os_error("ResumeThread")
        finally:
            k32.CloseHandle(thread)

    def kill_tree(self, proc: subprocess.Popen) -> None:
        """Kill ``proc`` and every descendant."""
        if self._job is not None:
            self._k32.TerminateJobObject(self._job, 1)
        elif os.name != "nt":
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGKILL)  # type: ignore[attr-defined]  # pylint: disable=no-member
        if proc.poll() is None:
            proc.kill()

    def close(self) -> None:
        """Close the job handle (kill-on-close ends any survivor)."""
        job, self._job = self._job, None
        if job is not None:
            self._k32.CloseHandle(job)


__all__ = ["ProcessBounds"]
