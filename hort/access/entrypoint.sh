#!/bin/sh
set -e

STORE="${HORT_STORE_PATH:-/data/hort-access.json}"
ADMIN_PASSWORD="${HORT_ADMIN_PASSWORD:-ChangeMe123!}"

# Create data dir if needed
mkdir -p "$(dirname "$STORE")"

# Create admin user if store doesn't exist yet
if [ ! -f "$STORE" ]; then
    echo "Creating admin user..."
    python -c "
from hort.access.store import FileStore
from hort.access.auth import hash_password
s = FileStore('$STORE')
s.create_user('admin', hash_password('$ADMIN_PASSWORD'), 'Administrator')
print('Admin user created.')
"
fi

exec "$@"
