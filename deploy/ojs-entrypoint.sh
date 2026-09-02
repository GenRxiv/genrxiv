#!/bin/sh
# Custom OJS entrypoint: runs pre-start, patches config, starts Apache, then installs.

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

    # Check if install actually succeeded by looking for tables
    TABLES=$(php -r "
        \$conf = parse_ini_file('/var/www/html/config.inc.php', true);
        \$dsn = 'pgsql:host=' . \$conf['database']['host'] . ';dbname=' . \$conf['database']['name'];
        try {
            \$pdo = new PDO(\$dsn, \$conf['database']['username'], \$conf['database']['password']);
            \$count = \$pdo->query(\"SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'\")->fetchColumn();
            echo \$count;
        } catch (Exception \$e) {
            echo '0';
        }
    " 2>/dev/null)

    if [ "$TABLES" -gt "0" ] 2>/dev/null; then
        echo "[OJS Entrypoint] Database has $TABLES tables — marking as installed"
        sed -i 's/^installed = Off/installed = On/' /var/www/html/config.inc.php
    fi
fi

# Wait for Apache in the foreground
wait $APACHE_PID
