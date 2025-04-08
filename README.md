# Intention-Based GUI Test Migration for Mobile Apps using Large Language Models

## Resources

- Paper: [ISSTA25](https://doi.org/10.1145/3728978)
- Dataset: [Zenodo](https://doi.org/10.5281/zenodo.15174071)

## Abstract

Graphical User Interface (GUI) testing is one of the primary quality assurance methods for mobile apps. Manually
constructing high-quality test cases for GUI testing is costly and labor-intensive, leading to the development of
various automated approaches that migrate test cases from a source app to a target app. Existing approaches
predominantly treat this test migration task as a widget-matching problem, which performs well when the interaction
logic between apps remains consistent. However, they struggle with variations in interaction logic for specific
functionalities, a common scenario across different apps. To address this limitation, a novel approach named ITeM is
introduced in this paper for the test migration task. Unlike existing works that model the problem as a widget-matching
task, ITeM seeks a novel pathway by adopting a two-stage framework with the comprehension and reasoning capability of
Large Language Models: first, a transition-aware mechanism for generating test intentions; and second, a dynamic
reasoning-based mechanism for fulfilling these intentions. This approach maintains effectiveness regardless of
variations across the source and target apps' interaction logic. Experimental results on 35 real-world Android apps
across 280 test migration tasks demonstrate the superior effectiveness and efficiency of ITeM compared to
state-of-the-art approaches.

## Citation

Coming soon

## Code

### I. Requirement

- Appium 2.2.1
- Android SDK
- Android Emulator(6.0 && 11.0) with Google API
- Java 8
- Python 3.11

### II. Preparations

#### 1. Start Appium service

- Execute `appium` in the terminal

#### 2. Connect the Android Emulator and the computer

- This can be verified through executing `adb devices` in the terminal
- For a1 through a6, use an emulator running Android 6.0
- For a7, use an emulator running Android 11.0
- Move the mp3 file in the dataset to the emulator

#### 3. Install all the apps

- Install all the apps in the corresponding version of the Android emulator
- It is recommended to use `adb install -g [app name]` to install the apps with all permission

#### 4. Install the Python libraries

- `pip install -r requirements.txt`

#### 5. Change the API Key for GPT

- Change the value of `API_KEY` in gpt_client.py
- You can also use other models that support the openai api.

#### 6. Modify the configuration file

- Modify the `apk_path` in the config/app.yaml

#### 7. Create the folders

- Create the `assets` folder in the root path
- Create the folders `assets/GPT_Guidance`, `assets/GPT_Trace`, `assets/Intention`, `assets/Oracle`, and `assets/Trace`

### III. Running ITeM

#### 1. Execute the source test on the source app to get the record the trace

> **main_trace.py**
>
> - Change the parameters of `execute_test_case`, e.g. `execute_test_case('a11', 'b11')` to specify the source app and
    the functionality
> - Run main_trace.py to get the execution trace

#### 2. Generate the test intentions of the source test

> **main_generate_intentions.py**
>
> - Change the parameters of `generate_test_intentions`, e.g. `generate_test_intentions('a11', 'b11')` to specify the
    source app and the functionality
> - Run main_generate_intentions.py to generate the test intentions

#### 3. Migrate the intentions on the target app

> **main_migrate_intentions.py**
>
> - Change the parameters of `perform_test_intentions`, e.g. `perform_test_intentions('a11', 'b11', 'a12')` to specify
    the source and target apps, as well as the functionality
> - Run main_migrate_intentions.py to start the intention migration tasks

#### 4. Migrate the oracles on the target app

> **main_migrate_oracles.py**
>
> - Change the parameters of `migration_test_oracles`, e.g. `migration_test_oracles('a11', 'b11', 'a12', False)`, to
    specify the source and target apps, as well as the functionality.
> - Ensure that the GPT trace has been generated for the migration task. This can be verified in the `assets/GPT_Trace/`
    directory
> - If the GPT trace has not been generated or has been deleted, set the `execution` parameter to `True`, e.g.,
    `migration_test_oracles('a11', 'b11', 'a12', True)`
> - Run main_migrate_oracles.py to start the oracle migration tasks