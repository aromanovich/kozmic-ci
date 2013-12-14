#!/bin/bash
if [[ -z $KOZMIC_CONFIG ]]; then
    if [[ ! -f ./kozmic/config_local.py ]]; then
        echo -e "./kozmic/config_local.py does not exist."\
                "\nPlease create it using ./kozmic/config_local.py-dist as an example."
        exit 1
    fi
    KOZMIC_CONFIG=kozmic.config_local.TestingConfig
fi

PYTHONPATH=.:$PYTHONPATH KOZMIC_CONFIG=$KOZMIC_CONFIG py.test ./tests "$@"
