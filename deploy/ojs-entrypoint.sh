#!/bin/sh
# Custom OJS entrypoint: runs pre-start, patches config, starts Apache, installs, then patches again.

# Run the pre-start (certs, apache config) but skip the CLI install
PKP_CLI_INSTALL=0 /usr/local/bin/pkp-pre-start

# Patch the config BEFORE install (for DB connection)
ojs-config-patch.sh

# Start Apache in the background
/usr/local/bin/apache2-foreground &
APACHE_PID=$!

# Wait for Apache to be ready
echo "[OJS Entrypoint] Waiting for Apache..."
for i in $(seq 1 30); do
    if curl -s -o /dev/null http://localhost:80/ 2>/dev/null; then
        echo "[OJS Entrypoint] Apache is ready"
        break
    fi
    sleep 1
done

# Run the CLI install if OJS is not yet installed
if grep -q 'installed = Off' /var/www/html/config.inc.php; then
    echo "[OJS Entrypoint] Running OJS CLI install..."
    /usr/local/bin/pkp-cli-install
    # Patch AGAIN after install (install resets allowed_hosts)
    ojs-config-patch.sh
fi

# Wait for Apache in the foreground
wait $APACHE_PID
