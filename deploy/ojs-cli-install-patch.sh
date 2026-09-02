#!/bin/sh
# Patched OJS CLI installer that uses the correct form fields and database driver.

echo "[PKP CLI Install] First time running this container, preparing..."

echo "[PKP CLI Install] Calling the install using pre-defined variables..."

# Wait for Apache to be ready
for i in $(seq 1 30); do
    if curl -s -o /dev/null http://localhost:80/ 2>/dev/null; then
        break
    fi
    sleep 1
done

curl -s -L "http://localhost:80/index/en/install/install" \
    --data "installing=0&installLanguage=en&adminUsername=${PKP_ADMIN_USER}&adminPassword=${PKP_ADMIN_PASSWORD}&adminPassword2=${PKP_ADMIN_PASSWORD}&adminEmail=${PKP_ADMIN_EMAIL}&locale=en&additionalLocales%5B%5D=en&timeZone=UTC&clientCharset=utf-8&connectionCharset=utf8&databaseCharset=utf8&filesDir=%2Fvar%2Fwww%2Ffiles&databaseDriver=postgres9&databaseHost=${PKP_DB_HOST}&databaseUsername=${PKP_DB_USER}&databasePassword=${PKP_DB_PASSWORD}&databaseName=${PKP_DB_NAME}&oaiRepositoryId=genrxiv.org&enableBeacon=0" \
    --compressed > /dev/null 2>&1

echo "[PKP CLI Install] DONE!"
