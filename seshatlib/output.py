import json
import sys

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"


class Reporter:
    def __init__(self, json_mode=False, color=True, stream=None):
        self.json_mode = json_mode
        self.stream = stream or sys.stdout
        self.color = color and self.stream.isatty()
        self.events = []

    def _c(self, code, text):
        return f"{code}{text}{RESET}" if self.color else text

    def _emit(self, line):
        if not self.json_mode:
            print(line, file=self.stream)

    def event(self, kind, message, **fields):
        self.events.append({"kind": kind, "message": message, **fields})

    def info(self, message, **fields):
        self.event("info", message, **fields)
        self._emit(message)

    def warn(self, message, **fields):
        self.event("warning", message, **fields)
        self._emit(self._c(YELLOW, f"warning: {message}"))

    def error(self, message, **fields):
        self.event("error", message, **fields)
        if self.json_mode:
            return
        print(self._c(RED, f"error: {message}"), file=sys.stderr)

    def change(self, kind, dest, bundle, detail=""):
        self.event("change", f"{kind} {dest}", change=kind, dest=dest, bundle=bundle, detail=detail)
        suffix = f"  ({detail})" if detail else ""
        self._emit(f"  {self._c(GREEN, kind):<18} {dest}{suffix}")

    def skip(self, dest, reason):
        self.event("skip", f"skip {dest}", dest=dest, reason=reason)
        self._emit(f"  {'skip':<10} {dest}  ({reason})")

    def blocked(self, dest, reason, key=None):
        where = f"{dest}#{key}" if key else dest
        self.event("blocked", f"blocked {where}", dest=dest, key=key, reason=reason)
        self._emit(f"  {self._c(RED, 'blocked'):<18} {where}  ({reason})")

    def table(self, headers, rows):
        self.event("table", "", headers=headers, rows=rows)
        if self.json_mode:
            return
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell)))
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        self._emit(self._c(BOLD, fmt.format(*headers)))
        for row in rows:
            self._emit(fmt.format(*[str(c) for c in row]))

    def finish(self, result=None):
        if self.json_mode:
            doc = {"result": result, "events": self.events}
            print(json.dumps(doc, indent=2), file=self.stream)
