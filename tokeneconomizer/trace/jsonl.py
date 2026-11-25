"""Reading a JSONL log line by line, skipping what does not parse."""
import json


def lines(path, *, strict=False):
    """Non-empty, stripped lines; suppress I/O errors unless the caller needs to detect them."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield line
    except OSError:
        if strict:
            raise


def records(path, *, strict=False):
    """Each line of a JSONL file that parses to a JSON object."""
    for line in lines(path, strict=strict):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev
