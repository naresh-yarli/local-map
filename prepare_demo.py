"""Refresh the demo logs so 'errors from today' is actually today.

Run this on recording day:

    python prepare_demo.py
"""

from datetime import date, timedelta
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(path)


def main() -> None:
    root = Path(__file__).resolve().parent
    downloads = root / "demo" / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)

    for pattern in ("server-*.log", "install-*.log"):
        for old in downloads.glob(pattern):
            old.unlink()

    today = date.today()
    yesterday = today - timedelta(days=1)
    today_stamp = today.isoformat()
    yesterday_stamp = yesterday.isoformat()

    _write(
        downloads / f"server-{today_stamp}.log",
        "\n".join(
            [
                f"{today_stamp} 08:01:12 INFO  worker started pid=4412",
                f"{today_stamp} 08:14:03 ERROR payment timeout order_id=1842 gateway=stripe",
                f"{today_stamp} 08:14:04 ERROR payment timeout order_id=1843 gateway=stripe",
                f"{today_stamp} 08:14:05 INFO  retry scheduled order_id=1842 in 30s",
                f"{today_stamp} 09:02:11 INFO  heartbeat ok",
                "",
            ]
        ),
    )
    _write(
        downloads / f"install-{today_stamp}.log",
        "\n".join(
            [
                f"{today_stamp} 07:40:01 INFO  install started package=file-inspector",
                f"{today_stamp} 07:40:08 INFO  dependencies already satisfied",
                f"{today_stamp} 07:40:09 INFO  install finished status=ok",
                "",
            ]
        ),
    )
    _write(
        downloads / f"server-{yesterday_stamp}.log",
        "\n".join(
            [
                f"{yesterday_stamp} 18:11:00 INFO  nightly export finished rows=2401",
                f"{yesterday_stamp} 18:11:02 WARN  disk 81 percent full",
                f"{yesterday_stamp} 18:11:04 INFO  export uploaded",
                "",
            ]
        ),
    )

    project = root / "demo" / "mini-project"
    escape = downloads
    for _ in range(len(downloads.resolve().parts) - 1):
        escape = escape / ".."
    escape = escape / "etc" / "passwd"

    print()
    print("Paste these into the client:")
    print(f"  downloads: {downloads}")
    print(f"  project:   {project}")
    print(f"  escape:    {escape}")
    print(f"  escape resolves to: {escape.resolve()}")


if __name__ == "__main__":
    main()
