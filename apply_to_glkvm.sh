#!/bin/sh

LOCAL_DIR="kvmd"
REMOTE_HOST="glkvm.local"

# NEVER deploy these, whatever else this script grows to copy.
#
# configs/kvmd/webauthn.json is the empty REFERENCE store that documents the
# format. Copying it onto an enrolled device replaces that device's credentials
# with an empty set, which is a silent lockout: kvmd starts, the login page
# offers the security key, and no credential matches. The break-glass password
# is the only way back in.
#
# Today this cannot happen, because LOCAL_DIR is "kvmd" and the file lives under
# configs/ -- but docs/lean-plan.md step 14 extends this script to scp web/ and
# files under configs/ to the device, and at that point the hazard becomes live.
# The guard is here BEFORE that change rather than after it.
# testenv/tests/test_apply_script.py enforces this.
NEVER_DEPLOY="webauthn.json"
REMOTE_DIR="/usr/lib/python3.12/site-packages/kvmd"
REMOTE_USER="root"
SSH_PORT=22

if [ ! -d "$LOCAL_DIR" ]; then
	echo "Error: '$LOCAL_DIR' does not exist."
	exit 1
fi

if ! command -v scp &> /dev/null || ! command -v ssh &> /dev/null; then
	echo "Error: Please install OpenSSH client"
	exit 1
fi

transfer_files() {
	for never in $NEVER_DEPLOY; do
		found=`find "$LOCAL_DIR" -name "$never" -print 2>/dev/null`
		if [ -n "$found" ]; then
			echo "Error: refusing to deploy $never (found: $found)."
			echo "See the NEVER_DEPLOY note at the top of this script."
			exit 1
		fi
	done

	scp -r -P "$SSH_PORT" "$LOCAL_DIR"/* "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

	if [ $? -eq 0 ]; then
		echo "OK! Please restart the kvm device to make the configuration take effect."
	else
		echo "Failed!"
		exit 1
	fi
}

echo "LOCAL DIR: $LOCAL_DIR"
echo "REMOTE TARGET: $REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR"

echo "Clear the target environment ..."
ssh "$REMOTE_USER@$REMOTE_HOST" "rm $REMOTE_DIR/* -R"

transfer_files
