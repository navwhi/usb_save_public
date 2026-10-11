#!/usr/bin/env python3
"""Lists the volumes of USB disks (partitions, or keys without a partition table) as JSON."""
import json
import re
import subprocess
import unicodedata

SYSTEM_MOUNTS = {"/", "/boot", "/boot/efi", "/home", "/usr", "/var", "[SWAP]"}
SKIP_FS = {"swap", "crypto_LUKS", "LVM2_member", "linux_raid_member"}


def suggest_name(*candidates):
    """Suggested key name: no accents, allowed characters only ("Café Notes" -> "Cafe_Notes")."""
    for text in candidates:
        ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_text).strip("._-")[:64]
        if name:
            return name
    return "key"


raw = subprocess.run(
    ["lsblk", "-J", "-p", "-o",
     "NAME,TYPE,TRAN,SIZE,FSTYPE,LABEL,UUID,MODEL,MOUNTPOINT"],
    capture_output=True, text=True, check=True,
).stdout
data = json.loads(raw)

volumes = []
for disk in data.get("blockdevices", []):
    if (disk.get("tran") or "").lower() != "usb":
        continue
    for vol in [disk] + disk.get("children", []):
        fstype = vol.get("fstype") or ""
        mountpoint = vol.get("mountpoint") or ""
        if not fstype or fstype in SKIP_FS or mountpoint in SYSTEM_MOUNTS:
            continue
        volumes.append({
            "path": vol.get("name"),
            "size": vol.get("size") or "?",
            "fstype": fstype,
            "label": vol.get("label") or "",
            "uuid": vol.get("uuid") or "",
            "model": (disk.get("model") or "").strip(),
            "mountpoint": mountpoint,
            "suggested_name": suggest_name(vol.get("label"), vol.get("uuid")),
        })

print(json.dumps(volumes))
