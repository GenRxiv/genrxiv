#!/bin/sh
# Custom OJS entrypoint: runs pre-start, patches config, starts Apache, then installs.

# Run the pre-start (certs, apache config) but skip the CLI install
PKP_CLI_INSTALL=0 /usr/local/bin/pkp-pre-start

# Patch the config BEFORE install (for DB connection)
ojs-config-patch.sh

# Patch the template manager (fixes OJS 3.5.0.5 bug with undefined $site)
sh /usr/local/bin/ojs-template-manager-patch.sh

# Create usageStats directory with correct permissions
mkdir -p /var/www/html/files/usageStats/usageEventLogs
chown -R www-data:www-data /var/www/html/files/usageStats

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
    # Check if tables already exist (database was persisted)
    TABLES=$(php /usr/local/bin/ojs-check-tables.php 2>/dev/null)
    echo "[OJS Entrypoint] Existing tables: $TABLES"

    if [ "$TABLES" -gt "0" ] 2>/dev/null; then
        echo "[OJS Entrypoint] Database already has $TABLES tables — marking as installed"
        sed -i 's/^installed = Off/installed = On/' /var/www/html/config.inc.php
    else
        echo "[OJS Entrypoint] Running OJS CLI install..."
        /usr/local/bin/pkp-cli-install
        # Patch AGAIN after install (install resets allowed_hosts and app_key)
        ojs-config-patch.sh

        # Recheck tables after install
        TABLES=$(php /usr/local/bin/ojs-check-tables.php 2>/dev/null)
        if [ "$TABLES" -gt "0" ] 2>/dev/null; then
            echo "[OJS Entrypoint] Install created $TABLES tables — marking as installed"
            sed -i 's/^installed = Off/installed = On/' /var/www/html/config.inc.php
        fi
    fi
fi

# Activate the GenRxiv theme
php /usr/local/bin/ojs-activate-theme.php 2>/dev/null

# Create the GenRxiv journal if it doesn't exist
php /usr/local/bin/ojs-create-journal.php 2>/dev/null

# Configure ORCID
php /usr/local/bin/ojs-configure-orcid.php 2>/dev/null

# Activate custom plugins (AI disclosure, etc.)
php /usr/local/bin/ojs-activate-plugins.php 2>/dev/null

# Wait for Apache in the foreground
wait $APACHE_PID
