#!/usr/bin/env zsh
set -euo pipefail

LOGDIR="/root/kde-downgrade-backup-$(date +%F-%T)"
mkdir -p "$LOGDIR"
echo "Backing up dpkg selections and apt policy..." | tee "$LOGDIR/run.log"
dpkg --get-selections > "$LOGDIR/dpkg-selections.txt"
apt-mark showmanual > "$LOGDIR/manual-packages.txt"
apt update | tee -a "$LOGDIR/run.log"

# Get list of installed packages
pkgs=$(dpkg-query -W -f='${Package}\n')

echo "Scanning packages for version mismatches..." | tee -a "$LOGDIR/run.log"

for pkg in $pkgs; do
  # Skip kernel meta packages to avoid accidental kernel churn (optional)
  if [[ "$pkg" == linux-* ]]; then
    continue
  fi

  installed=$(apt-cache policy "$pkg" 2>/dev/null | awk '/Installed:/ {print $2}')
  candidate=$(apt-cache policy "$pkg" 2>/dev/null | awk '/Candidate:/ {print $2}')
  # If either is empty, skip
  if [[ -z "$installed" || -z "$candidate" ]]; then
    continue
  fi
  # Skip if nothing to change
  if [[ "$installed" == "$candidate" ]]; then
    continue
  fi
  # Skip if candidate is (none)
  if [[ "$candidate" == "(none)" ]]; then
    echo "Skipping $pkg (candidate: none)" | tee -a "$LOGDIR/run.log"
    continue
  fi

  # Show brief policy info to user
  echo "----------------------------------------"
  echo "Package: $pkg"
  echo "Installed: $installed"
  echo "Candidate: $candidate"
  echo
  apt-cache policy "$pkg" | sed -n '1,10p'
  echo
  read -q "reply?Downgrade $pkg from $installed → $candidate? (y/N) "
  echo
  if [[ "$reply" =~ ^[Yy]$ ]]; then
    echo "Downgrading $pkg ..." | tee -a "$LOGDIR/run.log"
    # Try to install the candidate version (allow downgrades)
    if apt install --allow-downgrades -y "${pkg}=${candidate}" 2>&1 | tee -a "$LOGDIR/${pkg}.log"; then
      echo "SUCCESS: $pkg downgraded to $candidate" | tee -a "$LOGDIR/run.log"
    else
      echo "FAIL: $pkg failed to downgrade. Attempting to fix broken deps..." | tee -a "$LOGDIR/run.log"
      apt --fix-broken install -y 2>&1 | tee -a "$LOGDIR/fix-broken.log" || true
    fi
  else
    echo "Skipped $pkg" | tee -a "$LOGDIR/run.log"
  fi
done

echo "Final fix-broken + full-upgrade pass..." | tee -a "$LOGDIR/run.log"
apt --fix-broken install -y 2>&1 | tee -a "$LOGDIR/fix-broken.log" || true
apt full-upgrade -y 2>&1 | tee -a "$LOGDIR/full-upgrade.log" || true

echo "Done. Logs and backups in $LOGDIR"
echo "If the desktop packages still not consistent, paste $LOGDIR/full-upgrade.log here and I'll help interpret."
