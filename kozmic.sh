# Start all the required services
/etc/init.d/mysql start

# Create test database
mysql -uroot -e'CREATE DATABASE kozmic_test CHARACTER SET utf8 COLLATE utf8_general_ci;'

# Install requirements
pip install -r ./requirements/basic.txt
pip install -r ./requirements/dev.txt

# Run tests
cp kozmic/config_local.py-kozmic kozmic/config_local.py
KOZMIC_CONFIG=kozmic.config_local.KozmicTestingConfig ./test.sh
