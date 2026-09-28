"""
Over-the-air updates of the controller's code.

The dashboard's **Update controller** button publishes a manifest on
``<prefix>/<id>/firmware/update`` (see docs/MQTT.md)::

    {"version": "3f9a0c1b2d4e", "name": "1.1.0", "url": "http://192.168.1.20:8081/",
     "files": [{"path": "controller.py", "sha256": "...", "size": 17342}, ...]}

``version`` is the exact *build* (a hash of the files; 1.0.0 controllers
compare it, so it keeps that key) and ``name`` the version people read
(``version.py``). ``firmware.json`` keeps the build under ``version`` too.

The manifest arrives over the logged-in MQTT link, so it is trusted; the
files come over plain HTTP from the server's ``greenhouse-firmware`` service
and each one must match its SHA-256 and size or nothing changes.

1. :func:`stage` downloads the files that differ from what's installed into
   ``ota_new/``.
2. :func:`install` records the plan in ``firmware.json`` (``pending``), moves
   the old files to ``ota_old/``, moves the new ones in, marks it
   ``installed`` and the controller restarts.
3. ``boot.py`` counts restarts while an update is pending. If the new code
   hasn't reached the broker after ``MAX_BOOTS`` starts (a crash loop), or the
   file swap was cut short (power cut), it puts the old files back.
4. :func:`confirm` (called when the new code first reaches the broker) ends
   the trial and deletes the old files. New code that runs but can't reach
   the broker restarts itself after ``CONFIRM_WITHIN_MS`` (``controller.py``),
   which counts as a failed start.

``boot.py`` and ``main.py`` (the loader that catches import errors) are never
replaced over the air, nor are the settings files. Everything here works on
CPython too, which is how the tests run it.
"""
import binascii
import hashlib
import json
import os

STATE_FILE = "firmware.json"
VERSION_FILE = "version.py"
OLDEST_NAME = "1.0.0"  # code from before version.py existed
STAGE_DIR = "ota_new"
BACKUP_DIR = "ota_old"
MAX_BOOTS = 3  # must match boot.py
CONFIRM_WITHIN_MS = 10 * 60 * 1000
MAX_FILES = 64
CHUNK = 1024
TIMEOUT_S = 10
# Files an update may never touch.
KEEP = ("boot.py", "main.py", "config.json", "settings.json", STATE_FILE, "wifi_unverified")


class UpdateError(Exception):
    """An update could not be downloaded or checked; nothing was changed."""


# --- state file ----------------------------------------------------------------


def read_state():
    """
    Read ``firmware.json``.

    Returns:
        dict: The update state; empty when there is none (code copied by hand).
    """
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def write_state(state):
    """
    Replace ``firmware.json`` in one step.

    Args:
        state (dict): New state.
    """
    temporary = STATE_FILE + ".tmp"
    with open(temporary, "w") as f:
        json.dump(state, f)
    try:
        os.rename(temporary, STATE_FILE)
    except OSError:  # Windows won't rename over a file (tests only)
        os.remove(STATE_FILE)
        os.rename(temporary, STATE_FILE)


def current_version():
    """
    Name the installed code.

    Returns:
        str: The version from the last update or install, or ``"unknown"``.
    """
    return read_state().get("version") or "unknown"


def version_name(path=VERSION_FILE):
    """
    The installed code's version as people read it, from ``version.py``.

    Read from the file rather than imported, so it is right even between an
    update's file swap and the restart.

    Args:
        path (str): The version file.

    Returns:
        str: e.g. ``"1.1.0"``; ``"1.0.0"`` when there is no ``version.py``
        (it arrived after 1.0.0).
    """
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("VERSION"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return OLDEST_NAME


def is_pending():
    """bool: True while a new version is on trial (not yet confirmed)."""
    return bool(read_state().get("pending"))


# --- files -----------------------------------------------------------------


def exists(path):
    """Tell whether a file or folder exists."""
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def is_dir(path):
    """Tell whether a path is a folder."""
    try:
        return os.stat(path)[0] & 0x4000 != 0
    except OSError:
        return False


def makedirs(path):
    """
    Create a folder and its parents (no error if they exist).

    Args:
        path (str): e.g. ``"ota_new/lib/umqtt"``.
    """
    current = ""
    for part in path.split("/"):
        if not part:
            continue
        current = current + "/" + part if current else part
        if not exists(current):
            os.mkdir(current)


def remove_tree(path):
    """
    Delete a folder and everything in it (no error if it doesn't exist).

    Args:
        path (str): Folder.
    """
    if not exists(path):
        return
    if not is_dir(path):
        os.remove(path)
        return
    for name in os.listdir(path):
        remove_tree(path + "/" + name)
    os.rmdir(path)


def parent(path):
    """The folder part of a path (``""`` for a top-level file)."""
    return path.rsplit("/", 1)[0] if "/" in path else ""


def file_sha256(path):
    """
    Hash a file.

    Args:
        path (str): File.

    Returns:
        str | None: Hex SHA-256, or None if the file doesn't exist.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                block = f.read(CHUNK)
                if not block:
                    break
                digest.update(block)
    except OSError:
        return None
    return binascii.hexlify(digest.digest()).decode()


# --- manifest ----------------------------------------------------------------


def valid_path(path):
    """
    Tell whether a manifest path is a safe place for code.

    Args:
        path: Path from the manifest.

    Returns:
        bool: True for a relative ``.py`` path, inside this folder, that is
        not one of the ``KEEP`` files and not in the update folders.
    """
    if not isinstance(path, str) or not path.endswith(".py") or path in KEEP:
        return False
    parts = path.split("/")
    if parts[0] in ("", STAGE_DIR, BACKUP_DIR) or ".." in parts or "" in parts:
        return False
    return all(c.isalpha() or c.isdigit() or c in "_-." for part in parts for c in part)


def valid_manifest(manifest):
    """
    Check an update message.

    Args:
        manifest: Decoded JSON from ``firmware/update``.

    Returns:
        bool: True if it names a version, an ``http://`` URL and a list of
        files with safe paths, SHA-256 hashes and sizes.
    """
    if not isinstance(manifest, dict):
        return False
    version, url, files = manifest.get("version"), manifest.get("url"), manifest.get("files")
    if not isinstance(version, str) or not version or not isinstance(url, str) or not url.startswith("http://"):
        return False
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        return False
    for entry in files:
        if not isinstance(entry, dict) or not valid_path(entry.get("path")):
            return False
        sha, size = entry.get("sha256"), entry.get("size")
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            return False
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            return False
    return True


# --- download ------------------------------------------------------------------


def split_url(url):
    """
    Split an ``http://host[:port]/path`` URL.

    Args:
        url (str): URL.

    Returns:
        tuple[str, int, str]: Host, port (default 80) and path (default ``/``).

    Raises:
        UpdateError: If it isn't a plain http URL.
    """
    if not url.startswith("http://"):
        raise UpdateError("not an http:// address: " + url)
    rest = url[len("http://"):]
    hostport, slash, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    try:
        port = int(port) if port else 80
    except ValueError:
        raise UpdateError("bad port in " + url)
    if not host:
        raise UpdateError("no host in " + url)
    return host, port, slash + path if slash else "/"


def download(url, dest, sha256, size, feed=None):
    """
    Fetch one file over HTTP and check it.

    Args:
        url (str): File address.
        dest (str): Where to save it (its folder must exist).
        sha256 (str): Expected hex SHA-256.
        size (int): Expected size in bytes.
        feed (callable | None): Called while downloading (watchdog feed).

    Raises:
        UpdateError: On a network error, an HTTP error, or a size or hash
        mismatch (the partial file is deleted).
    """
    import socket

    host, port, path = split_url(url)
    digest = hashlib.sha256()
    received = 0
    sock = socket.socket()
    try:
        sock.settimeout(TIMEOUT_S)
        sock.connect(socket.getaddrinfo(host, port)[0][-1])
        request = "GET {} HTTP/1.0\r\nHost: {}\r\n\r\n".format(path, host)
        sock.send(request.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(256)
            if not chunk or len(head) > 4096:
                raise UpdateError("no reply from " + host)
            head += chunk
        head, _, body = head.partition(b"\r\n\r\n")
        status = head.split(b"\r\n")[0].split(b" ")
        if len(status) < 2 or status[1] != b"200":
            raise UpdateError("{} answered {}".format(url, b" ".join(status[1:]).decode()))
        with open(dest, "wb") as f:
            while True:
                if body:
                    received += len(body)
                    if received > size:
                        break
                    digest.update(body)
                    f.write(body)
                if feed:
                    feed()
                body = sock.recv(CHUNK)
                if not body:
                    break
    except OSError as err:
        _discard(dest)
        raise UpdateError("download of {} failed: {}".format(url, err))
    finally:
        sock.close()
    if received != size or binascii.hexlify(digest.digest()).decode() != sha256:
        _discard(dest)
        raise UpdateError("{} is damaged (size or checksum wrong)".format(url))


def _discard(path):
    """Delete a file if it exists."""
    try:
        os.remove(path)
    except OSError:
        pass


# --- stage, install, confirm ---------------------------------------------------


def stage(manifest, feed=None):
    """
    Download every file that differs from the installed one into ``ota_new/``.

    Args:
        manifest (dict): A :func:`valid_manifest` update message.
        feed (callable | None): Watchdog feed.

    Returns:
        list[str]: Paths that will change (empty if the code is already current).

    Raises:
        UpdateError: If any file fails; ``ota_new/`` is removed and the
        installed code is untouched.
    """
    remove_tree(STAGE_DIR)
    base = manifest["url"] if manifest["url"].endswith("/") else manifest["url"] + "/"
    changed = []
    try:
        for entry in manifest["files"]:
            path = entry["path"]
            if file_sha256(path) == entry["sha256"]:
                continue
            target = STAGE_DIR + "/" + path
            makedirs(parent(target))
            download(base + "files/" + path, target, entry["sha256"], entry["size"], feed)
            changed.append(path)
    except Exception:
        remove_tree(STAGE_DIR)
        raise
    return changed


def install(manifest, changed):
    """
    Swap the staged files in and put the new version on trial.

    ``firmware.json`` is written before anything moves, so ``boot.py`` can
    undo a swap that a power cut interrupted. The caller restarts the board.

    Args:
        manifest (dict): The update message.
        changed (list[str]): Paths returned by :func:`stage`.
    """
    remove_tree(BACKUP_DIR)
    state = {
        "version": manifest["version"],
        "previous": current_version(),
        "name": manifest.get("name") or manifest["version"],
        "previous_name": version_name(),
        "pending": True,
        "installed": False,
        "boots": 0,
        "changed": changed,
        "new_files": [path for path in changed if not exists(path)],
    }
    write_state(state)
    for path in changed:
        if exists(path):
            makedirs(parent(BACKUP_DIR + "/" + path))
            os.rename(path, BACKUP_DIR + "/" + path)
        if parent(path):
            makedirs(parent(path))
        os.rename(STAGE_DIR + "/" + path, path)
    state["installed"] = True
    write_state(state)
    remove_tree(STAGE_DIR)


def confirm():
    """
    End the trial: the new version reached the broker, so keep it.

    Returns:
        bool: True if a pending update was confirmed.
    """
    state = read_state()
    if not state.get("pending"):
        return False
    if state.get("previous_name"):
        detail = "Updated from {} to {}".format(state["previous_name"], state.get("name"))
    else:
        detail = "Updated from {}".format(state.get("previous"))
    write_state({"version": state.get("version"), "pending": False, "result": "updated", "detail": detail})
    remove_tree(BACKUP_DIR)
    return True


def mark_current(version):
    """
    Record the installed version without changing files (they already match).

    Args:
        version (str): Version name.
    """
    write_state({"version": version, "pending": False})


def take_result():
    """
    Read, once, how the last update ended.

    Returns:
        tuple[str, str] | None: ``(result, detail)`` such as
        ``("updated", "Updated from ...")`` or ``("rolled_back", ...)``, or None.
        The result is cleared so it is reported only once.
    """
    state = read_state()
    result = state.pop("result", None)
    if result is None:
        return None
    detail = state.pop("detail", "")
    write_state(state)
    return result, detail
