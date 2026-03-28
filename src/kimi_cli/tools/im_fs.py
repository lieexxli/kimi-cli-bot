"""Extra filesystem tools for IM non-admin users.

All tools enforce that paths stay within the session work_dir.
These are injected only for non-admin IM users who don't have the Shell tool.
"""

import shutil
from pathlib import Path
from typing import override

from kaos.path import KaosPath
from kosong.tooling import CallableTool2, ToolReturnValue
from pydantic import BaseModel, Field

from kimi_cli.soul.agent import Runtime
from kimi_cli.tools.utils import ToolResultBuilder
from kimi_cli.utils.path import is_within_workspace


def _resolve(path_str: str, work_dir: KaosPath) -> Path:
    """Resolve a path string relative to work_dir, returning an absolute Path."""
    work_dir_local = work_dir.unsafe_to_local_path()
    p = Path(path_str)
    p = (work_dir_local / p).resolve() if not p.is_absolute() else p.resolve()
    return p


def _check_within(path: Path, work_dir: KaosPath) -> str | None:
    """Return an error string if path is outside work_dir, else None."""
    kaos_path = KaosPath.unsafe_from_local_path(path)
    if not is_within_workspace(kaos_path, work_dir):
        return f"Path is outside your workspace: {path}"
    return None


# ---------------------------------------------------------------------------
# DeleteFile
# ---------------------------------------------------------------------------


class _DeleteParams(BaseModel):
    path: str = Field(description="Path to the file or empty directory to delete.")


class DeleteFile(CallableTool2[_DeleteParams]):
    name: str = "DeleteFile"
    description: str = (
        "Delete a file or empty directory within your workspace. "
        "The path must be inside your working directory."
    )
    params: type[_DeleteParams] = _DeleteParams

    def __init__(self, runtime: Runtime):
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR

    @override
    async def __call__(self, params: _DeleteParams) -> ToolReturnValue:
        builder = ToolResultBuilder()
        target = _resolve(params.path, self._work_dir)
        if err := _check_within(target, self._work_dir):
            return builder.error(err, brief="Path outside workspace")
        if not target.exists():
            return builder.error(f"Path does not exist: {target}", brief="Not found")
        try:
            if target.is_dir():
                target.rmdir()  # only removes empty dirs
            else:
                target.unlink()
        except OSError as e:
            return builder.error(str(e), brief="Delete failed")
        return builder.ok(f"Deleted: {params.path}")


# ---------------------------------------------------------------------------
# MoveFile
# ---------------------------------------------------------------------------


class _MoveParams(BaseModel):
    source: str = Field(description="Source path (file or directory).")
    destination: str = Field(description="Destination path.")


class MoveFile(CallableTool2[_MoveParams]):
    name: str = "MoveFile"
    description: str = (
        "Move or rename a file or directory within your workspace. "
        "Both source and destination must be inside your working directory."
    )
    params: type[_MoveParams] = _MoveParams

    def __init__(self, runtime: Runtime):
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR

    @override
    async def __call__(self, params: _MoveParams) -> ToolReturnValue:
        builder = ToolResultBuilder()
        src = _resolve(params.source, self._work_dir)
        dst = _resolve(params.destination, self._work_dir)
        if err := _check_within(src, self._work_dir):
            return builder.error(err, brief="Path outside workspace")
        if err := _check_within(dst, self._work_dir):
            return builder.error(err, brief="Path outside workspace")
        if not src.exists():
            return builder.error(f"Source does not exist: {src}", brief="Not found")
        try:
            shutil.move(str(src), str(dst))
        except OSError as e:
            return builder.error(str(e), brief="Move failed")
        return builder.ok(f"Moved: {params.source} → {params.destination}")


# ---------------------------------------------------------------------------
# CopyFile
# ---------------------------------------------------------------------------


class _CopyParams(BaseModel):
    source: str = Field(description="Source file path.")
    destination: str = Field(description="Destination file path.")


class CopyFile(CallableTool2[_CopyParams]):
    name: str = "CopyFile"
    description: str = (
        "Copy a file within your workspace. "
        "Both source and destination must be inside your working directory."
    )
    params: type[_CopyParams] = _CopyParams

    def __init__(self, runtime: Runtime):
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR

    @override
    async def __call__(self, params: _CopyParams) -> ToolReturnValue:
        builder = ToolResultBuilder()
        src = _resolve(params.source, self._work_dir)
        dst = _resolve(params.destination, self._work_dir)
        if err := _check_within(src, self._work_dir):
            return builder.error(err, brief="Path outside workspace")
        if err := _check_within(dst, self._work_dir):
            return builder.error(err, brief="Path outside workspace")
        if not src.exists():
            return builder.error(f"Source does not exist: {src}", brief="Not found")
        if src.is_dir():
            return builder.error(
                "CopyFile only supports files, not directories.", brief="Is a directory"
            )
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        except OSError as e:
            return builder.error(str(e), brief="Copy failed")
        return builder.ok(f"Copied: {params.source} → {params.destination}")


# ---------------------------------------------------------------------------
# MakeDir
# ---------------------------------------------------------------------------


class _MakeDirParams(BaseModel):
    path: str = Field(description="Directory path to create.")


class MakeDir(CallableTool2[_MakeDirParams]):
    name: str = "MakeDir"
    description: str = "Create a directory (including parents) within your workspace."
    params: type[_MakeDirParams] = _MakeDirParams

    def __init__(self, runtime: Runtime):
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR

    @override
    async def __call__(self, params: _MakeDirParams) -> ToolReturnValue:
        builder = ToolResultBuilder()
        target = _resolve(params.path, self._work_dir)
        if err := _check_within(target, self._work_dir):
            return builder.error(err, brief="Path outside workspace")
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return builder.error(str(e), brief="Mkdir failed")
        return builder.ok(f"Created directory: {params.path}")


# ---------------------------------------------------------------------------
# StatFile
# ---------------------------------------------------------------------------


class _StatParams(BaseModel):
    path: str = Field(description="Path to inspect.")


class StatFile(CallableTool2[_StatParams]):
    name: str = "StatFile"
    description: str = (
        "Get metadata of a file or directory within your workspace (size, type, modification time)."
    )
    params: type[_StatParams] = _StatParams

    def __init__(self, runtime: Runtime):
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR

    @override
    async def __call__(self, params: _StatParams) -> ToolReturnValue:
        builder = ToolResultBuilder()
        target = _resolve(params.path, self._work_dir)
        if err := _check_within(target, self._work_dir):
            return builder.error(err, brief="Path outside workspace")
        if not target.exists():
            return builder.error(f"Path does not exist: {target}", brief="Not found")
        try:
            st = target.stat()
            import datetime

            mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            kind = "directory" if target.is_dir() else "file"
            size = f"{st.st_size:,} bytes" if kind == "file" else "-"
            info = f"path: {params.path}\ntype: {kind}\nsize: {size}\nmodified: {mtime}"
        except OSError as e:
            return builder.error(str(e), brief="Stat failed")
        return builder.ok(info)
