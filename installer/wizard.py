"""
The greenhouse installer: a step-by-step window (PySide6 ``QWizard``).

Start it with ``setup.bat`` (Windows) or ``setup.sh`` (macOS, Linux), which
prepare Python and run ``python -m installer``. Pages:

1. **Welcome**: what happens next; *Update* for an existing installation.
2. **Packages**: installs the server's Python packages.
3. **Your greenhouse**: town (for weather and sunrise), time zone and the
   dashboard password; creates the database.
4. **Messaging**: sets up the MQTT broker on this computer (or uses one you
   already have) with a login for the server and each controller.
5. **Start the server**: systemd services on Linux; on Windows and macOS it
   starts now and whenever you log in.
6. **Controller**: sets up a Pico W over USB (MicroPython, Wi-Fi, code) and
   waits for it to come online. Can be skipped in favour of the setup
   hotspot (dashboard: Settings, Controllers).
7. **Done**: where to find the dashboard.

The work itself is in ``steps.py``, ``broker.py`` and ``pico.py``; pages run
it through :meth:`InstallerWizard.run_task` (a background thread, so the
window stays responsive; the tests swap in a synchronous runner).
"""
import getpass
import subprocess
import sys
import time
import urllib.request
from zoneinfo import available_timezones

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from installer import broker, pico, steps

TITLE = "Greenhouse setup"


# --- running work in the background ---------------------------------------------


class Worker(QObject):
    """Runs ``task(log)`` in a thread; ``log`` sends lines to the window."""

    line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self):
        """Run the task and report how it ended (never raises)."""
        try:
            message = self.task(self.line.emit)
        except Exception as err:  # shown to the user, not a crash
            self.finished.emit(False, str(err))
        else:
            self.finished.emit(True, message or "")


class TaskPage(QWizardPage):
    """A page with a log box and a button that runs its task."""

    button_text = "Start"

    def __init__(self, title, intro):
        super().__init__()
        self.setTitle(title)
        self.ok = False
        self.running = False
        self.layout_ = QVBoxLayout(self)
        self.intro = QLabel(intro)
        self.intro.setWordWrap(True)
        self.layout_.addWidget(self.intro)
        self.form = QFormLayout()
        self.layout_.addLayout(self.form)
        self.button = QPushButton(self.button_text)
        self.button.clicked.connect(self.start)
        self.layout_.addWidget(self.button)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.layout_.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace"))
        self.layout_.addWidget(self.log, 1)

    def task(self, log):
        """The work (override). Returns a message for the status line."""
        raise NotImplementedError

    def before(self):
        """Read the page's fields before the task starts; return an error or None."""
        return None

    def start(self):
        """Run :meth:`task` in the background."""
        problem = self.before()
        if problem:
            self.status.setText("⚠ " + problem)
            return
        self.running = True
        self.ok = False
        self.button.setEnabled(False)
        self.status.setText("Working…")
        self.completeChanged.emit()
        self.wizard().run_task(self.task, self.log.appendPlainText, self.done)

    def done(self, ok, message):
        """Show how the task ended."""
        self.running = False
        self.ok = ok
        self.button.setEnabled(True)
        self.status.setText(("✔ " if ok else "✖ ") + (message or ("Done." if ok else "Something went wrong.")))
        self.completeChanged.emit()

    def isComplete(self):  # noqa: N802 (Qt naming)
        return self.ok and not self.running


# --- pages ---------------------------------------------------------------------


class WelcomePage(QWizardPage):
    """What the installer does; update an existing installation."""

    def __init__(self):
        super().__init__()
        self.setTitle("Welcome")
        layout = QVBoxLayout(self)
        text = QLabel(
            "This sets up your greenhouse on this computer, step by step:\n\n"
            "  1. the programs the server needs\n"
            "  2. your location, time zone and dashboard password\n"
            "  3. the messaging service the controller talks to\n"
            "  4. starting the server (and again whenever this computer starts)\n"
            "  5. your Pico W controller, over a USB cable\n\n"
            "Keep this computer switched on and connected to the same Wi-Fi network as the "
            "greenhouse. You can run this again at any time to change a setting."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        self.update_button = QPushButton("Update this installation to the newest version")
        self.update_button.setVisible(steps.is_git_checkout())
        self.update_button.clicked.connect(self.update)
        layout.addWidget(self.update_button)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)

    def update(self):
        """Pull the newest code, install packages and upgrade the database."""
        def task(log):
            for command, cwd in steps.update_commands():
                log("$ " + " ".join(command))
                if steps.run(command, cwd, log) != 0:
                    raise RuntimeError("Update failed at: " + " ".join(command[:3]))
            return ("Updated. Restart the server (or this computer) to use the new version; controllers "
                    "show Update available on the dashboard's Controllers page.")

        self.update_button.setEnabled(False)
        self.status.setText("Updating…")
        self.wizard().run_task(task, lambda line: None, self._updated)

    def _updated(self, ok, message):
        self.update_button.setEnabled(True)
        self.status.setText(("✔ " if ok else "✖ ") + message)


class PackagesPage(TaskPage):
    """Install the server's Python packages."""

    button_text = "Install again"

    def __init__(self):
        super().__init__("Programs", "Installing the programs the server needs. This takes a few minutes "
                                     "the first time and needs an internet connection.")

    def initializePage(self):  # noqa: N802
        if not self.ok and not self.running:
            self.start()

    def task(self, log):
        if steps.run(steps.pip_install_command(), steps.REPO_DIR, log) != 0:
            raise RuntimeError("Installing failed. Check the internet connection and try again.")
        return "Everything is installed."


class GreenhousePage(QWizardPage):
    """Location, time zone and dashboard password; creates the database."""

    def __init__(self):
        super().__init__()
        self.setTitle("Your greenhouse")
        self.setSubTitle("The location is used for the weather and for sunrise and sunset.")
        form = QFormLayout(self)
        self.town = QLineEdit()
        self.town.setPlaceholderText("Town or city, e.g. Reno")
        find = QPushButton("Find")
        find.clicked.connect(self.find_town)
        row = QHBoxLayout()
        row.addWidget(self.town, 1)
        row.addWidget(find)
        form.addRow("Town", row)
        self.places = QComboBox()
        self.places.currentIndexChanged.connect(self.pick_place)
        form.addRow("", self.places)
        self.latitude = QDoubleSpinBox(decimals=4, minimum=-90, maximum=90)
        self.longitude = QDoubleSpinBox(decimals=4, minimum=-180, maximum=180)
        form.addRow("Latitude", self.latitude)
        form.addRow("Longitude", self.longitude)
        self.zone = QComboBox()
        self.zone.setEditable(True)
        self.zone.addItems(sorted(z for z in available_timezones() if "/" in z) + ["UTC"])
        form.addRow("Time zone", self.zone)
        self.password = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.again = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        form.addRow("Dashboard password", self.password)
        form.addRow("Password again", self.again)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        form.addRow(self.note)
        self.results = []

    def initializePage(self):  # noqa: N802
        env = steps.read_env()
        for box, key in ((self.latitude, "LATITUDE"), (self.longitude, "LONGITUDE")):
            try:
                box.setValue(float(env.get(key, "")))
            except ValueError:
                pass
        self.zone.setCurrentText(env.get("TIMEZONE") or "UTC")
        if env.get("APP_PASSWORD_HASH"):
            self.password.setPlaceholderText("Leave empty to keep the current password")

    def find_town(self):
        """Look the town up and list the matches."""
        self.results = steps.geocode(self.town.text().strip())
        self.places.clear()
        self.places.addItems([p["label"] for p in self.results])
        if not self.results:
            self.note.setText("No place found (or no internet). Enter the latitude and longitude instead.")

    def pick_place(self, index):
        """Fill in the chosen place's position and time zone."""
        if 0 <= index < len(self.results):
            place = self.results[index]
            self.latitude.setValue(place["latitude"])
            self.longitude.setValue(place["longitude"])
            self.zone.setCurrentText(place["timezone"])
            self.note.setText("")

    def validatePage(self):  # noqa: N802
        """Save the settings and create (or upgrade) the database."""
        zone = self.zone.currentText().strip()
        if zone not in available_timezones():
            self.note.setText("Choose a time zone from the list.")
            return False
        values = {"LATITUDE": f"{self.latitude.value():.4f}", "LONGITUDE": f"{self.longitude.value():.4f}",
                  "TIMEZONE": zone}
        keep = not self.password.text() and steps.read_env().get("APP_PASSWORD_HASH")
        if not keep:
            problem = steps.password_problem(self.password.text(), self.again.text())
            if problem:
                self.note.setText(problem)
                return False
            values["APP_PASSWORD_HASH"] = steps.password_hash(self.password.text())
        steps.update_env(values)
        lines = []
        if steps.run(steps.upgrade_db_command(), steps.SERVER_DIR, lines.append) != 0:
            self.note.setText("The database couldn't be created:\n" + "\n".join(lines[-5:]))
            return False
        return True


class BrokerPage(TaskPage):
    """Set up the MQTT broker, or check an existing one."""

    button_text = "Set up messaging"

    def __init__(self):
        super().__init__(
            "Messaging",
            "The controller and the server talk through a small messaging service (an MQTT broker). "
            "Every connection needs a login, which this step creates.")
        self.local = QRadioButton("Set it up on this computer (recommended)")
        self.existing = QRadioButton("Use a broker I already have")
        self.local.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.local)
        group.addButton(self.existing)
        self.host = QLineEdit()
        self.port = QSpinBox(minimum=1, maximum=65535, value=1883)
        self.user = QLineEdit()
        self.secret = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.form.addRow(self.local)
        self.form.addRow(self.existing)
        for label, field in (("Address", self.host), ("Port", self.port), ("Server login", self.user),
                             ("Password", self.secret)):
            self.form.addRow(label, field)
        self.local.toggled.connect(self.show_fields)
        self.show_fields()

    def show_fields(self):
        """Enable the address fields only for an existing broker."""
        for field in (self.host, self.port, self.user, self.secret):
            field.setEnabled(self.existing.isChecked())

    def before(self):
        self.use_local = self.local.isChecked()
        self.values = (self.host.text().strip(), self.port.value(), self.user.text().strip() or None,
                       self.secret.text() or None)
        if not self.use_local and not self.values[0]:
            return "Enter the broker's address."
        return None

    def task(self, log):
        steps.server_import_path()
        from core import device_credentials, setup_code

        env = steps.read_env()
        public = env.get("PUBLIC_HOST") or setup_code.lan_address() or ""
        if not self.use_local:
            host, port, user, secret = self.values
            ok, message = broker.check_login(host, port, user, secret)
            if not ok:
                raise RuntimeError(message)
            steps.update_env({"MQTT_HOST": host, "MQTT_PORT": str(port), "MQTT_USERNAME": user or "",
                              "MQTT_PASSWORD": secret or "", "PUBLIC_HOST": public})
            return message + " Controllers need their own logins on that broker (see docs/RUNBOOK.md)."

        stored = device_credentials.load()
        server_password = env.get("MQTT_PASSWORD") if env.get("MQTT_USERNAME") == broker.SERVER_USER else None
        logins = {broker.SERVER_USER: server_password or device_credentials.new_password()}
        for device_id in sorted(set(stored) | {1}):
            login = stored.get(device_id) or {"user": device_credentials.device_user(device_id),
                                              "password": device_credentials.new_password()}
            device_credentials.save(device_id, login["user"], login["password"])
            logins[login["user"]] = login["password"]
        device_ids = sorted(set(stored) | {1})
        os_name = steps.system()
        if os_name == "linux":
            script = broker.stage_linux(logins, device_ids)
            log("Asking for the administrator password to set up Mosquitto…")
            code = steps.run(["pkexec", "sh", str(script)], steps.REPO_DIR, log)
            pico.remove_folder(script.parent)
            if code != 0:
                raise RuntimeError("Setting up Mosquitto failed (or the password was cancelled).")
            port = 1883
            ok, message = broker.check_login("localhost", port, broker.SERVER_USER, logins[broker.SERVER_USER])
        else:
            steps.server_import_path()
            from run_all import find_mosquitto

            if find_mosquitto() is None:
                log("Installing Mosquitto…")
                if steps.run(broker.install_command(os_name), steps.REPO_DIR, log) != 0 or find_mosquitto() is None:
                    raise RuntimeError("Mosquitto couldn't be installed. Install it from https://mosquitto.org/download/ "
                                       "and try again.")
            port = broker.choose_port()
            conf = broker.write_local(logins, device_ids, port)
            process = subprocess.Popen([find_mosquitto(), "-c", str(conf)], cwd=steps.SERVER_DIR,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                time.sleep(1.5)
                ok, message = broker.check_login("localhost", port, broker.SERVER_USER, logins[broker.SERVER_USER])
            finally:
                process.terminate()
        if not ok:
            raise RuntimeError(message)
        steps.update_env({"MQTT_HOST": "localhost", "MQTT_PORT": str(port), "MQTT_USERNAME": broker.SERVER_USER,
                          "MQTT_PASSWORD": logins[broker.SERVER_USER], "PUBLIC_HOST": public})
        return f"Messaging is ready on port {port}. Controllers will reach it at {public or 'this computer'}."


class ServicesPage(TaskPage):
    """Start the server, now and at every start of this computer."""

    button_text = "Start the server"

    def __init__(self):
        super().__init__("Start the server", "")
        self.autostart = QCheckBox("Start the server whenever I log in to this computer")
        self.autostart.setChecked(True)
        self.form.addRow(self.autostart)
        self.open_button = QPushButton("Open the dashboard")
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.url())))
        self.layout_.insertWidget(3, self.open_button)

    def initializePage(self):  # noqa: N802
        linux = steps.system() == "linux"
        self.autostart.setVisible(not linux)
        self.intro.setText("Installs the server as system services that start with the computer and restart "
                      "themselves if they stop (asks for the administrator password)." if linux else
                      "Starts the dashboard and the background services.")

    def url(self):
        return steps.dashboard_url("localhost")

    def before(self):
        self.want_autostart = self.autostart.isChecked()
        return None

    def task(self, log):
        os_name = steps.system()
        if os_name == "linux":
            if steps.run(steps.systemd_install_command(getpass.getuser()), steps.REPO_DIR, log) != 0:
                raise RuntimeError("Installing the services failed (or the password was cancelled).")
        else:
            if self.want_autostart or os_name == "macos":
                log(f"Start at log-in: {steps.install_autostart(os_name)}")
            steps.start_server(os_name)
        for _ in range(60):
            try:
                urllib.request.urlopen(self.url(), timeout=2)
                return f"The server is running. Dashboard: {self.url()}"
            except OSError:
                time.sleep(1)
        raise RuntimeError("The dashboard didn't start within a minute. Try Start the server again.")


class ControllerPage(TaskPage):
    """Set up a Pico W over USB."""

    button_text = "Set up the controller"

    def __init__(self):
        super().__init__(
            "Controller",
            "Plug the Pico W into this computer with a USB data cable. A brand-new Pico: hold its BOOTSEL "
            "button while plugging it in. No cable? Skip this; the dashboard's Settings, Controllers page "
            "explains how to set it up from your phone.")
        self.found = QLabel("Looking for the controller…")
        self.form.addRow("Found", self.found)
        self.ssid = QLineEdit()
        self.wifi_password = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.device = QSpinBox(minimum=1, maximum=99, value=1)
        self.form.addRow("Wi-Fi network", self.ssid)
        self.form.addRow("Wi-Fi password", self.wifi_password)
        self.form.addRow("Controller number", self.device)
        self.band_note = QLabel("")
        self.band_note.setWordWrap(True)
        self.form.addRow(self.band_note)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.look)
        self.bootsel = None
        self.ports = []

    def initializePage(self):  # noqa: N802
        ssid, is_5ghz = pico.current_wifi()
        if ssid and not self.ssid.text():
            self.ssid.setText(ssid)
        if is_5ghz:
            self.band_note.setText(f"⚠ {ssid} looks like a 5 GHz network. The Pico W only works on 2.4 GHz; "
                                   "many routers offer both under different names.")
        self.look()
        self.timer.start(2000)

    def cleanupPage(self):  # noqa: N802
        self.timer.stop()

    def look(self):
        """Check the USB ports and drives for a Pico."""
        if self.running:
            return
        self.bootsel = pico.find_bootsel()
        self.ports = [] if self.bootsel else pico.find_serial_ports()
        if self.bootsel:
            self.found.setText(f"A new Pico ({self.bootsel[1]}) at {self.bootsel[0]}: MicroPython will be installed.")
        elif self.ports:
            self.found.setText(f"A Pico with MicroPython on {self.ports[0]}.")
        else:
            self.found.setText("Nothing yet. Plug in the Pico (holding BOOTSEL if it is new).")

    def isComplete(self):  # noqa: N802
        return not self.running  # optional: Next also skips it

    def before(self):
        steps.server_import_path()
        from core import device_credentials, setup_code

        if not (self.bootsel or self.ports):
            return "No controller found. Plug it in and wait a moment."
        env = steps.read_env()
        device_id = self.device.value()
        login = device_credentials.get(device_id)
        if env.get("MQTT_USERNAME") and login is None:
            return (f"There's no broker login for controller {device_id}. Set up messaging on this computer "
                    "(previous page), or add its login on the dashboard.")
        host = env.get("PUBLIC_HOST") or setup_code.lan_address()
        if not host:
            return "This computer's network address couldn't be found."
        if not self.ssid.text().strip():
            return "Enter the Wi-Fi network name."
        self.plan = {
            "bootsel": self.bootsel,
            "answers": {
                "wifi_ssid": self.ssid.text().strip(), "wifi_password": self.wifi_password.text(),
                "mqtt_broker": host, "mqtt_port": int(env.get("MQTT_PORT") or 1883),
                "mqtt_user": login["user"] if login else "", "mqtt_password": login["password"] if login else "",
                "device_id": device_id, "timezone": env.get("TIMEZONE") or "UTC",
            },
            "server": ("localhost" if env.get("MQTT_HOST") in (None, "", "localhost") else env["MQTT_HOST"],
                       int(env.get("MQTT_PORT") or 1883), env.get("MQTT_USERNAME") or None,
                       env.get("MQTT_PASSWORD") or None),
        }
        return None

    def task(self, log):
        return set_up_controller(self.plan, log)


def set_up_controller(plan, log, wait=pico.wait_for_port, sleep=time.sleep):
    """
    The controller steps, in order (see ``pico.py``).

    Args:
        plan (dict): ``bootsel`` (drive and board, or None), ``answers`` for
            ``config.json`` and the ``server`` broker login used to watch for it.
        log (callable): Progress lines.
        wait (callable): Waits for the serial port.
        sleep (callable): Pause.

    Returns:
        str: Success message.

    Raises:
        RuntimeError: When a step fails.
    """
    if plan["bootsel"]:
        drive, board = plan["bootsel"]
        url = pico.latest_uf2_url(board)
        log(f"Downloading MicroPython: {url}")
        uf2 = urllib.request.urlopen(url, timeout=60).read()
        pico.flash_micropython(drive, uf2)
        log("Installing MicroPython (the Pico restarts)…")
        if not wait(timeout=60):
            raise RuntimeError("The Pico didn't come back after installing MicroPython. Unplug it and plug it in again.")
    port = wait(timeout=10)
    if not port:
        raise RuntimeError("The controller isn't connected.")
    log("Restarting the controller…")
    steps.run(pico.reset_command(port), steps.REPO_DIR, log)
    sleep(2)
    port = wait(timeout=20)
    if not port:
        raise RuntimeError("The controller didn't come back after restarting.")
    config, warning = pico.controller_config(plan["answers"])
    if warning:
        log("Note: " + warning)
    folder = pico.staging_folder()
    try:
        paths = pico.stage_files(config, folder)
        log(f"Copying {len(paths)} files to the controller…")
        if steps.run(pico.copy_command(port, folder, paths), steps.REPO_DIR, log) != 0:
            raise RuntimeError("Copying to the controller failed. Unplug it, plug it in again and retry.")
    finally:
        pico.remove_folder(folder)
    answers = plan["answers"]
    log(f"Waiting for controller {answers['device_id']} to join {answers['wifi_ssid']} and come online…")
    host, port_number, user, secret = plan["server"]
    if not pico.wait_online(answers["device_id"], host, port_number, user, secret):
        raise RuntimeError("The controller didn't come online within 2 minutes. Check the Wi-Fi password; "
                           "if it's wrong, the controller starts its setup hotspot so you can fix it from a phone.")
    return f"Controller {answers['device_id']} is online."


class DonePage(QWizardPage):
    """Where to go next."""

    def __init__(self):
        super().__init__()
        self.setTitle("All set")
        layout = QVBoxLayout(self)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setOpenExternalLinks(True)
        layout.addWidget(self.text)
        layout.addStretch(1)

    def initializePage(self):  # noqa: N802
        steps.server_import_path()
        from core import setup_code

        env = steps.read_env()
        url = steps.dashboard_url(env.get("PUBLIC_HOST") or setup_code.lan_address())
        self.text.setText(
            f"<p>Your greenhouse dashboard: <a href='{url}'>{url}</a> (from any phone or computer on your "
            "Wi-Fi). Log in with the password you chose.</p>"
            "<p><b>Adding or re-connecting a controller:</b> Settings, Controllers on the dashboard.</p>"
            "<p><b>Updates:</b> run this setup again and choose <i>Update</i>. Controllers then show "
            "<i>Update available</i> on the Controllers page.</p>")


class InstallerWizard(QWizard):
    """The installer window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{TITLE} {steps.server_version()}")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(720, 560)
        self.threads = []
        for page in (WelcomePage(), PackagesPage(), GreenhousePage(), BrokerPage(), ServicesPage(),
                     ControllerPage(), DonePage()):
            self.addPage(page)

    def run_task(self, task, on_line, on_done):
        """
        Run ``task(log)`` in a background thread.

        Args:
            task (callable): Work; raises to fail, returns a message.
            on_line (callable): Receives progress lines (in the window's thread).
            on_done (callable): Receives ``(ok, message)`` at the end.
        """
        thread = QThread(self)
        worker = Worker(task)
        worker.moveToThread(thread)
        worker.line.connect(on_line)
        worker.finished.connect(on_done)
        worker.finished.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.finished.connect(lambda: self.threads.remove((thread, worker)))
        self.threads.append((thread, worker))
        thread.start()

    def reject(self):
        """Ask before closing while something is still running."""
        if self.threads and QMessageBox.question(self, TITLE, "Setup is still working. Stop anyway?") \
                != QMessageBox.StandardButton.Yes:
            return
        super().reject()


def main() -> int:
    """Open the installer window."""
    app = QApplication.instance() or QApplication(sys.argv)
    wizard = InstallerWizard()
    wizard.show()
    return app.exec()
