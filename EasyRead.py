import tkinter as tk
import subprocess
import threading
import re
import os
import queue

# ================== GUI COLOR THEME ==================
BG_MAIN   = "#1e1e1e"
BG_PANEL  = "#2a2a2a"
BG_LOG    = "#111111"
FG_TEXT   = "#dddddd"
FG_ACCENT = "#4fc3f7"
FG_OK     = "#66bb6a"
FG_WARN   = "#ffa726"
FG_ERR    = "#ef5350"

FONT_UI   = ("Segoe UI", 10)
FONT_LOG  = ("Consolas", 10)
# =====================================================

# gw.exe must be in SAME folder as this script
GW = os.path.join(os.path.dirname(__file__), "gw.exe")

FORMATS = [
    "ibm.1440","ibm.720","ibm.1200","ibm.360","atarist.720","amiga.amigados"
]

DUMP_DIR = os.path.join(os.path.dirname(__file__), "dumps")
os.makedirs(DUMP_DIR, exist_ok=True)


class App:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Greaseweazle EASYREAD")
        self.root.configure(bg=BG_MAIN)

        self.filename_var = tk.StringVar(value="disk.img")

        self.log_queue = queue.Queue()
        self.root.after(100, self.process_log_queue)

        # ---------- TOP PANEL ----------
        top = tk.Frame(self.root, bg=BG_PANEL, padx=10, pady=8)
        top.pack(fill="x")

        tk.Label(top, text="Filename:", bg=BG_PANEL, fg=FG_TEXT, font=FONT_UI)\
            .pack(side=tk.LEFT)

        tk.Entry(top, textvariable=self.filename_var, width=30,
                 bg="white", fg="black", font=FONT_UI)\
            .pack(side=tk.LEFT, padx=8)

        tk.Button(top, text="READ DISK",
                  bg=FG_ACCENT, fg="black", activebackground="#81d4fa",
                  font=FONT_UI, relief="flat",
                  command=self.start_auto)\
            .pack(side=tk.LEFT, padx=10)

        # ---------- LOG FRAME ----------
        log_frame = tk.Frame(self.root, bg=BG_MAIN)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.logbox = tk.Text(
            log_frame,
            bg=BG_LOG,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=FONT_LOG,
            relief="flat",
            bd=0
        )
        self.logbox.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(log_frame, command=self.logbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.logbox.config(yscrollcommand=scrollbar.set)

        self.logbox.tag_config("ok", foreground=FG_OK)
        self.logbox.tag_config("warn", foreground=FG_WARN)
        self.logbox.tag_config("err", foreground=FG_ERR)
        self.logbox.tag_config("accent", foreground=FG_ACCENT)

    # ---------------- THREAD SAFE LOG ----------------

    def log(self, text):
        self.log_queue.put(text)

    def process_log_queue(self):
        while not self.log_queue.empty():
            text = self.log_queue.get()

            tag = None
            if "OK" in text:
                tag = "ok"
            elif "❌" in text or "not" in text.lower():
                tag = "err"
            elif "[3/4]" in text or "Trying" in text:
                tag = "accent"

            self.logbox.insert(tk.END, text, tag)
            self.logbox.see(tk.END)

        self.root.after(100, self.process_log_queue)

    # ---------------- DRIVE DETECT ----------------

    def detect_drive(self):
        self.log("\n[1/4] Searching for drive...\n")

        for d in ["A", "B", "0", "1", "2"]:
            self.log(f"Trying drive {d}...\n")

            result = subprocess.run(
                [GW, "read", os.devnull, f"--drive={d}", "--revs=0"],
                capture_output=True,
                text=True
            )

            out = result.stdout + result.stderr

            if "No Index" not in out and "Track 0 not found" not in out:
                self.log(f"Drive {d} OK\n")
                return d

            self.log("No drive response.\n")

        self.log("No drive found.\n")
        return None

    # ---------------- FLUX READ ----------------

    def read_flux(self, drive):
        self.log("\n[2/4] Reading flux...\n")
        flux_file = os.path.join(DUMP_DIR, "auto.scp")

        process = subprocess.Popen(
            [GW, "read", flux_file, f"--drive={drive}", "--revs=5"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        for line in process.stdout:
            self.log(line)

        process.wait()
        return flux_file

    # ---------------- FORMAT DETECT ----------------

    def detect_format(self, flux_file):
        self.log("\n[3/4] Testing formats...\n")

        best_score = 0
        best_format = None

        for fmt in FORMATS:
            self.log(f"\nTrying format: {fmt}\n")

            result = subprocess.run(
                [GW, "convert", flux_file, "temp.img", f"--format={fmt}"],
                capture_output=True, text=True
            )

            out = result.stdout + result.stderr
            self.log(out)

            m = re.search(r"Found (\d+) sectors of (\d+)", out)
            crc = re.search(r"(\d+) CRC", out)

            if m:
                found = int(m.group(1))
                total = int(m.group(2))
                score = found / total

                crc_penalty = int(crc.group(1)) if crc else 0
                score_adjusted = max(0.0, score - (crc_penalty * 0.01))

                self.log(f"Score: {score_adjusted:.3f}\n")

                if score_adjusted > best_score:
                    best_score = score_adjusted
                    best_format = fmt

                if score >= 0.98:
                    self.log("Very confident match — stopping search.\n")
                    return fmt

        return best_format

    # ---------------- MAIN AUTO ----------------

    def auto_process(self):
        self.log("\n=== AUTOMATIC DISK READ STARTED ===\n")

        drive = self.detect_drive()
        if not drive:
            return

        flux = self.read_flux(drive)

        fmt = self.detect_format(flux)
        if not fmt:
            self.log("Format not detected.\n")
            return

        self.log(f"\n[4/4] Best format: {fmt}\n")

        final_path = os.path.join(DUMP_DIR, self.filename_var.get())
        self.log("\nWriting final image...\n")

        process = subprocess.Popen(
            [GW, "convert", flux, final_path, f"--format={fmt}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        for line in process.stdout:
            self.log(line)

        process.wait()
        self.log("\n=== DONE ===\n")

    def start_auto(self):
        threading.Thread(target=self.auto_process, daemon=True).start()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
