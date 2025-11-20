#!/bin/bash
cd ./.venv
# python3.10 ../src/main.py -c ../config/collision_handshake_demo.json
# python3.10 ../src/main.py -c ../config/random_wp_test_bounded.json
# python3.10 ../src/main.py -c ../config/random_wp_test_unbounded.json
python3.10 ../src/main.py -c ../config/random_wp_message_cleanup.json
# python3.10 ../src/main.py -c ../config/spin_model_test_selection_bounded.json
# python3.10 ../src/main.py -c ../config/spin_model_test_flocking_unbounded.json
# python3.10 ../src/main.py -c ../config/random_waypoint_hierarchy_unbounded.json
cd ../
