#!/bin/bash
cd ./.venv
# python3 ../src/main.py -c ../config/random_wp_test.json
# python3 ../src/main.py -c ../config/spin_model_test_selection.json
python3 ../src/main.py -c ../config/spin_model_test_flocking.json
cd ../