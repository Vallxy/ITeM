import json
import shutil
import time
from pathlib import Path
from typing import Tuple, List

from appium import webdriver
from appium.options.android import UiAutomator2Options
from omegaconf import OmegaConf

from gpt_client import GPTClient


class TestMigrator:
    INTENTION_PATH = r'assets/Intention'

    RESULT_PATH = r'assets/Result'

    TRACE_PATH = r'assets/Trace'

    GPT_TRACE_PATH = r'assets/GPT_Trace'

    ORACLE_PATH = r'assets/Oracle'

    ITeM_PATH = r'ITeM_Dataset'

    def __init__(self):
        self.gpt_client = GPTClient()
        # e.g. {a11_b12:[action_trace], a11_b12:[],...}
        self.app_func_to_action_trace = {}
        self.test_cases = {}
        self.load_test_cases()

    def get_action_trace(self, app_tag, func_tag):
        trace_path = Path(self.TRACE_PATH)
        action_trace_path = trace_path / app_tag / func_tag / 'action_trace.json'
        with open(action_trace_path, mode='r', encoding='utf-8') as f:
            self.app_func_to_action_trace[f'{app_tag}_{func_tag}'] = json.load(f)

    def get_screen_list(self, app_tag, func_tag) -> Tuple[List[Path], List[Path]]:
        trace_path = Path(self.TRACE_PATH)
        functionality_path = trace_path / app_tag / func_tag
        screen_before_path_list = []
        screen_after_path_list = []
        for file_path in functionality_path.glob('*'):
            if 'json' in file_path.name:
                continue
            elif 'a.xml' in file_path.name:
                screen_before_path_list.append(file_path)
            elif 'b.xml' in file_path.name:
                screen_after_path_list.append(file_path)
        return screen_before_path_list, screen_after_path_list

    def generate_test_intentions(self, app_tag, func_tag):
        self.get_action_trace(app_tag, func_tag)
        action_trace = self.app_func_to_action_trace[f'{app_tag}_{func_tag}']
        screen_before_path_list, screen_after_path_list = self.get_screen_list(app_tag, func_tag)
        responses, time = self.gpt_client.generate_test_intention(action_trace, screen_before_path_list,
                                                                  screen_after_path_list)

        intention_path = Path(self.INTENTION_PATH)
        func_intention_path = intention_path / func_tag
        if not func_intention_path.exists():
            func_intention_path.mkdir()
        app_intention_path = func_intention_path / f'{app_tag}.txt'
        if app_intention_path.exists():
            app_intention_path.unlink()
        app_intention_path.touch()
        with open(app_intention_path, mode='w', encoding='utf-8') as f:
            for response in responses:
                f.write(response + '\n')
        # store time to the file
        time_txt_path = func_intention_path / f'{app_tag}_time.txt'
        if not time_txt_path.exists():
            time_txt_path.touch()
        with open(time_txt_path, mode='w', encoding='utf-8') as f:
            f.write(str(time))

    def connect_device(self, desired_caps):
        appium_server_url = 'http://localhost:4723'
        driver = webdriver.Remote(appium_server_url, options=UiAutomator2Options().load_capabilities(desired_caps))
        time.sleep(15)
        return driver

    def load_test_cases(self):
        item_path = Path(self.ITeM_PATH)
        for category_json_path in item_path.glob('*'):
            for functionality_path in category_json_path.glob('*'):
                functionality_tag = functionality_path.stem
                if functionality_tag == 'subject_apps' or not functionality_path.is_dir():
                    continue
                base_folder_path = functionality_path / 'base'
                for json_path in base_folder_path.glob('*'):
                    app_tag = json_path.stem
                    if app_tag not in self.test_cases.keys():
                        self.test_cases[app_tag] = {}
                    app_test_cases = self.test_cases[app_tag]
                    with open(json_path, mode='r', encoding='utf-8') as f:
                        app_test_cases[functionality_tag] = json.load(f)
        test_cases_json_path = item_path / 'test_cases.json'
        if not test_cases_json_path.exists():
            test_cases_json_path.touch()
        with open(test_cases_json_path, mode='w', encoding='utf-8') as f:
            json.dump(self.test_cases, f)

    def migration_test_oracles(self, app_tag, func_tag, target_app_tag, execution=False):
        gpt_trace_path = Path(self.GPT_TRACE_PATH)
        original_trace_folder_path = Path(self.TRACE_PATH)
        oracle_path = Path(self.ORACLE_PATH)

        current_task_gpt_trace_folder_path = gpt_trace_path / f'{app_tag}_{func_tag}_{target_app_tag}'
        current_task_original_trace_folder_path = original_trace_folder_path / app_tag / func_tag
        current_task_oracle_folder_path = oracle_path / f'{app_tag}_{func_tag}_{target_app_tag}'
        if not current_task_oracle_folder_path.exists():
            current_task_oracle_folder_path.mkdir()
        current_task_oracle_path = current_task_oracle_folder_path / 'oracle.txt'
        if not current_task_oracle_path.exists():
            current_task_oracle_path.touch()
        current_task_messages_list_path = current_task_oracle_folder_path / 'messages_list.json'
        if not current_task_messages_list_path.exists():
            current_task_messages_list_path.touch()

        test_case = self.test_cases[app_tag][func_tag]
        if execution:
            app_config = OmegaConf.load('config/app.yaml')[target_app_tag]
            env_config = OmegaConf.load('config/env.yaml')['Appium']
            desired_caps = self.generate_desired_caps(app_config, env_config)
            driver = self.connect_device(desired_caps)
            self.gpt_client.perform_gpt_guidance(driver, current_task_gpt_trace_folder_path)
        oracle_list, messages_list = self.gpt_client.generate_oracle_from_gpt_trace(current_task_gpt_trace_folder_path,
                                                                                    test_case,
                                                                                    current_task_original_trace_folder_path,
                                                                                    current_task_oracle_folder_path)

        with open(current_task_oracle_path, mode='w', encoding='utf-8') as f:
            for oracle in oracle_list:
                f.write(oracle + '\n')

        self.store_json_file(messages_list, current_task_messages_list_path)

    def perform_test_intentions(self, intention_app_tag, intention_func_tag, target_app_tag):
        intention_path = Path(self.INTENTION_PATH)
        gpt_trace_path = Path(self.GPT_TRACE_PATH)
        current_migration_task_trace = gpt_trace_path / f'{intention_app_tag}_{intention_func_tag}_{target_app_tag}'
        if current_migration_task_trace.exists():
            shutil.rmtree(current_migration_task_trace)
        current_migration_task_trace.mkdir()
        txt_path = intention_path / intention_func_tag / f'{intention_app_tag}.txt'
        intention_list = []
        with open(txt_path, mode='r', encoding='utf-8') as f:
            intention_list = f.readlines()
        intention_list = [x.strip() for x in intention_list]

        app_config = OmegaConf.load('config/app.yaml')[target_app_tag]
        env_config = OmegaConf.load('config/env.yaml')['Appium']
        desired_caps = self.generate_desired_caps(app_config, env_config)
        driver = self.connect_device(desired_caps)
        action_trace, messages_list = self.gpt_client.perform_intention(intention_list, driver,
                                                                        current_migration_task_trace, desired_caps)

        current_intention_message_path = current_migration_task_trace / 'messages.json'
        current_intention_action_trace_path = current_migration_task_trace / 'action_trace.json'
        self.store_json_file(action_trace, current_intention_action_trace_path)
        self.store_json_file(messages_list, current_intention_message_path)

    def store_json_file(self, obj, path):
        if not path.exists():
            path.touch()
        with open(path, mode='w', encoding='utf-8') as f:
            json.dump(obj, f)

    def generate_desired_caps(self, app_config, env_config):
        desired_caps = {'appium-version': env_config['appium-version'],
                        'platformName': env_config['platformName'],
                        'platformVersion': env_config['platformVersion'],
                        'deviceName': env_config['deviceName'],
                        'automationName': env_config['automationName'],
                        'newCommandTimeout': env_config['newCommandTimeout'],
                        'appPackage': app_config['appPackage'],
                        'appActivity': app_config['appActivity']}
        if 'noReset' not in app_config:
            desired_caps['autoGrantPermissions'] = env_config['autoGrantPermissions']
        else:
            desired_caps['noReset'] = app_config['noReset']
        return desired_caps
