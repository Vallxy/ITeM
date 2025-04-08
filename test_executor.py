import json
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from omegaconf import OmegaConf
from selenium.common import WebDriverException
from selenium.webdriver import ActionChains


# Run the test case, capture the necessary data to build the trace
class TestExecutor:
    ITeM_PATH = r'ITeM_Dataset'

    TRACE_PATH = r'assets/Trace'

    ACTION_SLEEP_INTERVAL = 5

    def __init__(self):
        # {app_tag:{functionality_tag:[{test_action},{},{}]}}
        self.test_cases = {}
        self.load_test_cases()

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

    def execute_test_case(self, app_tag, functionality_tag):
        test_case = self.test_cases[app_tag][functionality_tag]
        app_config = OmegaConf.load('config/app.yaml')[app_tag]
        env_config = OmegaConf.load('config/env.yaml')['Appium']
        desired_caps = self.generate_desired_caps(app_config, env_config)
        trace_path = Path(self.TRACE_PATH)

        # create trace folders
        app_trace_folder = trace_path / app_tag
        if not app_trace_folder.exists():
            app_trace_folder.mkdir()
        app_func_trace_folder = app_trace_folder / functionality_tag
        if app_func_trace_folder.exists():
            shutil.rmtree(app_func_trace_folder)
        app_func_trace_folder.mkdir()

        action_trace = []
        driver = self.connect_device(desired_caps)
        for action_index, test_action in enumerate(test_case):
            self.execute_test_action(driver, test_action, app_func_trace_folder, action_index, action_trace)
        driver.quit()
        self.store_action_trace(action_trace, app_func_trace_folder)

    def store_action_trace(self, action_trace, app_func_trace_folder):
        action_trace_path = app_func_trace_folder / 'action_trace.json'
        if not action_trace_path.exists():
            action_trace_path.touch()
        with open(action_trace_path, mode='w', encoding='utf-8') as f:
            json.dump(action_trace, f)

    def execute_test_action(self, driver, test_action, app_func_trace_folder, action_index, action_trace):
        screenshot_before_path = app_func_trace_folder / f'{action_index}_a.png'
        screenshot_after_path = app_func_trace_folder / f'{action_index}_b.png'
        xml_before_path = app_func_trace_folder / f'{action_index}_a.xml'
        xml_after_path = app_func_trace_folder / f'{action_index}_b.xml'

        print(test_action)
        event_type = test_action['event_type']
        current_screen_xml = str(driver.page_source)

        driver.get_screenshot_as_file(str(screenshot_before_path))
        xml_root_before = ET.fromstring(str(driver.page_source))
        xml_tree_before = ET.ElementTree(xml_root_before)
        xml_tree_before.write(xml_before_path)
        match event_type:
            case 'gui':
                id = test_action['resource-id']
                content_desc = test_action['content-desc']
                text = test_action['text']
                clazz = test_action['class']
                el = self.find_element(id, clazz, text, content_desc, current_screen_xml, driver)
                self.record_action(el, action_trace, test_action)
                self.perform_gui_action(el, test_action['action'], driver)

            case 'SYS_EVENT':
                self.record_action(None, action_trace, test_action)
                self.perform_sys_event(test_action['action'], driver)

            case 'oracle':
                self.record_action(None, action_trace, test_action)
                self.perform_oracle(test_action['action'], driver)

        driver.get_screenshot_as_file(str(screenshot_after_path))
        xml_root_after = ET.fromstring(str(driver.page_source))
        xml_tree_after = ET.ElementTree(xml_root_after)
        xml_tree_after.write(xml_after_path)

    def perform_oracle(self, action, driver):
        pass

    def perform_sys_event(self, action, driver):
        action_name = action[0]
        if action_name == 'KEY_BACK':
            driver.back()
        elif action_name == 'SCROLL_DOWN':
            driver.swipe(500, 1000, 500, 200, 500)
        elif action_name == 'SCROLL_UP':
            driver.swipe(500, 200, 500, 1000, 500)
        # only for 1080*1920 resolution
        elif action_name == 'KEYBOARD_SEARCH':
            x_center = (1224 + 1440) // 2
            y_center = (2739 + 2959) // 2
            driver.tap([(x_center, y_center)], 100)
        else:
            assert False, 'Unknown SYS_EVENT'

    def get_child_node_list(self, root, child_node_list):
        has_child = False
        for child in root:
            has_child = True
            self.get_child_node_list(child, child_node_list)

        if not has_child:
            child_node_list.append(root)

    def get_parent_node_list(self, root, parent_node_list):
        has_child = False
        for child in root:
            has_child = True
            self.get_parent_node_list(child, parent_node_list)
        if has_child:
            parent_node_list.append(root)

    def find_element(self, id, clazz, text, content_desc, xml, driver):
        el = None
        root = ET.fromstring(xml)
        xml_node_list = []
        child_xml_node_list = []
        parent_xml_node_list = []
        self.get_child_node_list(root, child_xml_node_list)
        self.get_parent_node_list(root, parent_xml_node_list)
        xml_node_list.extend(child_xml_node_list)
        xml_node_list.extend(parent_xml_node_list)

        candidate_elements = {}
        for xml_node in xml_node_list:
            node_id = xml_node.attrib['resource-id'] if 'resource-id' in xml_node.attrib else ''
            node_clazz = xml_node.attrib['class'] if 'class' in xml_node.attrib else ''
            node_text = xml_node.attrib['text'] if 'text' in xml_node.attrib else ''
            node_content_desc = xml_node.attrib['content-desc'] if 'content-desc' in xml_node.attrib else ''

            if (id, text) == (node_id, node_text) and id != '' and text != '' and clazz != 'android.widget.EditText':
                ui_selector = f'new UiSelector().resourceId("{id}").text("{text}")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
                # set priority, the lower value, the higher priority
                candidate_elements[el] = 0

            elif (id, clazz) == (node_id, node_clazz) and id != '':
                ui_selector = f'new UiSelector().resourceId("{id}").className("{clazz}")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
                candidate_elements[el] = 1

            elif (id, text) == (node_id, node_text) and id != '' and text != '':
                ui_selector = f'new UiSelector().resourceId("{id}").text("{text}")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
                # set priority, the lower value, the higher priority
                candidate_elements[el] = 0

            elif (id, clazz) == (node_id, node_clazz) and id == '':
                if text == node_text and text != '':
                    ui_selector = f'new UiSelector().className("{clazz}").text("{text}")'
                    el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)

                elif content_desc == node_content_desc and content_desc != '':
                    ui_selector = f'new UiSelector().className("{clazz}").description("{content_desc}")'
                    el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)

                candidate_elements[el] = 2

            elif (id, clazz) == (
            node_id, node_clazz) and id == '' and text == '' and clazz == 'android.widget.EditText':
                ui_selector = f'new UiSelector().className("{clazz}")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
                candidate_elements[el] = 3

            elif (id, clazz) == (
            node_id, node_clazz) and id == '' and text == '' and clazz == 'android.widget.EditText':
                ui_selector = f'new UiSelector().className("{clazz}")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
                candidate_elements[el] = 3

        candidate_elements = sorted(candidate_elements.items(), key=lambda x: x[1], reverse=False)
        for candidate_element in candidate_elements:
            if candidate_element[0] is not None:
                el = candidate_element[0]
                break
        print(
            f'el:(id:{el.get_attribute("resource-id")}, text:{el.get_attribute("text")}, content-desc:{el.get_attribute("content-desc")})')
        print('================================================')
        return el

    def perform_gui_action(self, el, action, driver):
        action_name = action[0]
        if action_name == 'click':
            el.click()
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif 'send_keys' in action_name:
            # if the el is not edittext, click it to show the edittext, special for a15
            if el.get_attribute('class') == 'android.widget.TextView':
                el.click()
                time.sleep(1)
                ui_selector = f'new UiSelector().className("android.widget.EditText")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)

            elif el.get_attribute('class') == 'android.widget.EditText':
                el.click()
                time.sleep(1)

            value_for_input = action[1]
            # 'clear_and_send_keys', 'clear_and_send_keys_and_hide_keyboard', 'send_keys_and_hide_keyboard', 'send_keys_and_enter', 'send_keys'
            if action_name.startswith('clear'):
                el.clear()
            # in case clear the content and the original el is invalid
            try:
                el.send_keys(value_for_input)
            except Exception as e:
                ui_selector = f'new UiSelector().className("android.widget.EditText")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
                el.send_keys(value_for_input)
            if action_name.endswith('hide_keyboard'):
                self.hide_keyboard(driver)
            elif action_name.endswith('enter'):
                driver.press_keycode(66)
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif action_name == 'swipe_right':
            # e.g., {'x': 202, 'y': 265, 'width': 878, 'height': 57}
            rect = el.rect
            start_x, start_y, end_x, end_y = rect['x'] + rect['width'] / 4, rect['y'] + rect['height'] / 2, \
                                             rect['x'] + rect['width'] * 3 / 4, rect['y'] + rect['height'] / 2
            driver.swipe(start_x, start_y, end_x, end_y, 500)
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif action_name == 'long_press':
            ac = ActionChains(driver)
            ac.w3c_actions.pointer_action.click_and_hold(el)
            ac.w3c_actions.pointer_action.pause(2)
            ac.w3c_actions.pointer_action.release()
            ac.perform()
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        else:
            assert False, "Unknown action to be performed"

    def record_action(self, el, action_trace, test_action):
        if el is not None:
            bounds = el.get_attribute('bounds')
            if bounds is not None:
                test_action['bounds'] = bounds
        action_trace.append(test_action)

    def connect_device(self, desired_caps):
        appium_server_url = 'http://localhost:4723'
        driver = webdriver.Remote(appium_server_url, options=UiAutomator2Options().load_capabilities(desired_caps))
        time.sleep(15)
        return driver

    def launch_app(self, driver, desired_caps):
        driver.activate_app(desired_caps['appPackage'])
        time.sleep(20)

    def close_app(self, driver, desired_caps):
        try:
            driver.terminate_app(desired_caps['appPackage'])
            time.sleep(5)
        except:
            driver.terminate_app(desired_caps['appPackage'])

    def parse_method_name(self, method_name_raw):
        # e.g. <SixPM.RepresentativeTests: void testSignUp()>
        return method_name_raw.split(' ')[-1][:-3]

    def init_app_trace_storage(self, app_tag):
        app_trace_folder_path = Path(self.TRACE_PATH) / app_tag
        if not app_trace_folder_path.exists():
            app_trace_folder_path.mkdir()

    def init_method_trace_storage(self, app_name, method_name) -> Path:
        method_trace_folder_path = Path(self.TRACE_PATH) / app_name / method_name
        if not method_trace_folder_path.exists():
            method_trace_folder_path.mkdir()
        return method_trace_folder_path

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

    def hide_keyboard(self, driver):
        if driver.is_keyboard_shown:
            try:
                driver.hide_keyboard()
            except WebDriverException:
                pass