#!/bin/bash
# backup.sh - zip backup + rotate last N backups

# CONFIG - edit these if needed
APP_DIR="$HOME/mysite"       # <-- change this to your app directory if different
BACKUP_DIR="$HOME/backups"   # where backup zip files are stored
KEEP=7                       # keep last N backups

# derived vars
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
ZIPNAME="xeno-backup-${TIMESTAMP}.zip"
ZIPPATH="${BACKUP_DIR}/${ZIPNAME}"

# ensure backup dir exists
mkdir -p "$BACKUP_DIR"

# create zip (follow symlinks)
zip -r -q "$ZIPPATH" "$APP_DIR"

# rotate: remove older backups, keep $KEEP most recent
cd "$BACKUP_DIR" || exit 0
ls -1t xeno-backup-*.zip 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm --

# print result for logs
echo "Backup saved: $ZIPPATH"
