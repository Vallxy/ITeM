import re
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import openai
from alive_progress import alive_it
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import WebDriverException
from selenium.webdriver import ActionChains

from threshold import EXPLORATION_LIMIT
from util import get_current_package_name


class GPTClient:
    MODEL = 'gpt-4-turbo'
    # TODO set your api key
    API_KEY = ''

    ACTION_SLEEP_INTERVAL = 20

    GPT_GUIDANCE_PATH = r'assets/GPT_Guidance'

    def __init__(self):
        openai.api_key = self.API_KEY

    def generate_gui_event_prompt(self, action_trace, screen_before_path_list, screen_after_path_list):
        gui_event_prompt_list = []
        for i, test_action in enumerate(action_trace):
            event_type = test_action['event_type']
            action = test_action['action']
            action_name = action[0]

            if event_type == 'oracle':
                continue

            elif event_type == 'gui':
                id = test_action['resource-id']
                content_desc = test_action['content-desc']
                text = test_action['text']
                clazz = test_action['class']
                package = test_action['package']
                activity = test_action['activity']

                # relevant information
                app_info = f'current package:<{package}>,current activity:<{activity}>'
                if len(action) == 1:
                    action_info = f'operation type: <{action_name}>'
                else:
                    action_info = f'operation type: <{action_name}>, input value: <{action[1]}>'
                widget_info = f'id:<{id}>,content-desc:<{content_desc}>,text:<{text}>,class:<{clazz}>'
                widget_list_before = self.get_widget_list_from_xml(screen_before_path_list[i])
                widget_list_after = self.get_widget_list_from_xml(screen_after_path_list[i])
                app_prompt = f'The basic information of the app before performing the test action includes {app_info}.'
                action_prompt = f'The information of the executed test action includes {action_info}.'
                widget_prompt = f'The interacted widget associated with the executed test action includes {widget_info}.'
                screen_prompt = (
                    f'The GUI screen before performing the test action contains these widgets: {widget_list_before}.'
                    f'The GUI screen after performing the test action contains these widgets: {widget_list_after}.')
                gui_event_prompt = f'{app_prompt} {action_prompt} {widget_prompt} {screen_prompt}'
                gui_event_prompt_list.append(gui_event_prompt)

            elif event_type == 'SYS_EVENT':
                action_info = f'operation type: <{action_name}>'
                widget_list_before = self.get_widget_list_from_xml(screen_before_path_list[i])
                widget_list_after = self.get_widget_list_from_xml(screen_after_path_list[i])

                action_prompt = f'The information of the executed test action includes {action_info}.'
                screen_prompt = (
                    f'The GUI screen before performing the test action contains these widgets: {widget_list_before}.'
                    f'The GUI screen after performing the test action contains these widgets: {widget_list_after}.')
                gui_event_prompt = f'{action_prompt} {screen_prompt}'
                gui_event_prompt_list.append(gui_event_prompt)

        return gui_event_prompt_list

    def capture_current_screen_info(self, driver):
        screen_info = []
        xml_str = str(driver.page_source)
        root = ET.fromstring(xml_str)
        xml_node_list = []
        child_xml_node_list = []
        self.get_child_node_list(root, child_xml_node_list)
        xml_node_list.extend(child_xml_node_list)
        for xml_node in xml_node_list:
            if 'text' in xml_node.attrib and xml_node.attrib['text'] != '':
                screen_info.append(xml_node.attrib['text'])
                continue
            if 'content-desc' in xml_node.attrib and xml_node.attrib['content-desc'] != '':
                screen_info.append(xml_node.attrib['content-desc'])
                continue
            if 'resource-id' in xml_node.attrib and xml_node.attrib['resource-id'] != '':
                screen_info.append(xml_node.attrib['resource-id'])
                continue
        return screen_info

    def parse_fixed_parts(self, input_string):
        # Regular expression to extract fixed parts
        fixed_part_pattern = r'^<([^,]+), ([^,]+),.*\), (.+)>$'
        match = re.match(fixed_part_pattern, input_string)

        if match:
            position = match.group(1).strip()
            action = match.group(2).strip()
            additional_info = match.group(3).strip()
            return {
                'type': position,
                'action': action,
                'additional_info': additional_info
            }
        else:
            # Return None or a default dictionary if the format does not match
            return None

    def parse_and_perform_gpt_guidance(self, response_text, driver, action_trace, current_widget_list):
        guidance = re.search(r'<[^<>]+>', response_text).group()
        if '<Skip>' in response_text:
            self.record_action(None, action_trace, 'Skip')
            time.sleep(self.ACTION_SLEEP_INTERVAL)
            return '<Skip>'
        if '(resource-id:' not in guidance:
            # e.g. <Explore, click, 1, Empty>
            split_list = guidance.replace('<', '').replace('>', '').split(',')
            guidance_type = split_list[0].strip()
            operation_type = split_list[1].strip()
            widget_index = int(split_list[2].strip())
            input_value = self.process_input(','.join(split_list[3:]))
            if 0 <= widget_index < len(current_widget_list):
                element = current_widget_list[widget_index]
            else:
                element = {'resource-id': '', 'content-desc': '', 'text': '', 'class': ''}
            id = element['resource-id']
            text = element['text']
            clazz = element['class']
            content_desc = element['content-desc']
            widget_repr = f'(resource-id:{id}, class:{clazz}, content-desc:{content_desc}, text:{text})'
            print(f'guidance: {guidance}')
            print(f'index: {widget_index}, widget: {widget_repr}')
            print('=============================================')
            el = self.find_element(element, driver)

            possible_invalid_operation_list = ['click', 'long_click']
            if operation_type in possible_invalid_operation_list and (
                    widget_index == -1 or self.is_empty_widget(element)):
                operation_type = 'back'

            self.record_action(el, action_trace, operation_type)
            self.perform_gui_action(el, operation_type, input_value, driver)
            return f'<{guidance_type}, {operation_type}, {widget_repr}, {input_value}>'
        else:
            # e.g. <Exact, input_and_enter, (resource-id:de.baumann.browser:id/main_omnibox_input, class:android.widget.EditText, content-desc:, text:Search or type URL), https://www.ics.uci.edu>
            element = self.parse_element(guidance)
            guidance = self.parse_fixed_parts(guidance)
            operation_type = guidance['action']
            input_value = self.process_input(guidance['additional_info'])
            print(f'guidance: {guidance}')
            print(f'element: {element}')
            print('=============================================')
            el = self.find_element(element, driver)
            self.record_action(el, action_trace, operation_type)
            self.perform_gui_action(el, operation_type, input_value, driver)
            return re.search(r'<(.*?)>', response_text).group()

    def record_action(self, el, action_trace, operation_type):
        action = {'operation_type': operation_type}
        attrib_name_list = ['bounds', 'resource-id', 'content-desc', 'text']
        if el is not None:
            for attrib_name in attrib_name_list:
                attrib_value = el.get_attribute(attrib_name)
                if attrib_value is not None:
                    action[attrib_name] = attrib_value
        action_trace.append(action)

    def process_input(self, raw_str):
        result = raw_str.strip()
        if result.startswith('"') or result.startswith("\'"):
            result = result[1:-1]
        print(f'processed input: {result.strip()}')
        return result.strip()

    def perform_gui_action(self, el, operation_type, input_value, driver):

        print(f'operation:{operation_type} {input_value}')
        print('================================================')
        if operation_type == 'click':
            if el is None:
                print('el is None')
            else:
                el.click()
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'input':
            if el.get_attribute('class') == 'android.widget.TextView':
                el.click()
                time.sleep(1)
                ui_selector = f'new UiSelector().className("android.widget.EditText")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
            el.clear()
            time.sleep(1)
            el.send_keys(input_value)
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'input_and_enter':
            if el.get_attribute('class') == 'android.widget.TextView':
                el.click()
                time.sleep(1)
                ui_selector = f'new UiSelector().className("android.widget.EditText")'
                el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
            try:
                el.click()
                el.clear()
                el.send_keys(input_value)
                driver.press_keycode(66)
            except Exception as e:
                print(e)
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'long_click':
            ac = ActionChains(driver)
            ac.w3c_actions.pointer_action.click_and_hold(el)
            ac.w3c_actions.pointer_action.pause(2)
            ac.w3c_actions.pointer_action.release()
            ac.perform()
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'swipe_right':
            # e.g., {'x': 202, 'y': 265, 'width': 878, 'height': 57}
            if el is None:
                try:
                    driver.swipe(200, 960, 800, 960, 500)
                except Exception as e:
                    print(e)
                time.sleep(self.ACTION_SLEEP_INTERVAL)
            else:
                rect = el.rect
                start_x, start_y, end_x, end_y = rect['x'] + rect['width'] / 4, rect['y'] + rect['height'] / 2, \
                                                 rect['x'] + rect['width'] * 3 / 4, rect['y'] + rect['height'] / 2
                driver.swipe(start_x, start_y, end_x, end_y, 500)
                time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'swipe_left':
            # e.g., {'x': 202, 'y': 265, 'width': 878, 'height': 57}
            if el is None:
                try:
                    driver.swipe(800, 960, 200, 960, 500)
                except Exception as e:
                    print(e)
                time.sleep(self.ACTION_SLEEP_INTERVAL)
            else:
                rect = el.rect
                end_x, end_y, start_x, start_y = rect['x'] + rect['width'] / 4, rect['y'] + rect['height'] / 2, \
                                                 rect['x'] + rect['width'] * 3 / 4, rect['y'] + rect['height'] / 2
                driver.swipe(start_x, start_y, end_x, end_y, 500)
                time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'enter':
            driver.press_keycode(66)
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'back':
            driver.back()
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'scroll_down':
            try:
                driver.swipe(500, 1000, 500, 200, 500)
            except Exception as e:
                print(e)
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        elif operation_type == 'scroll_up':
            try:
                driver.swipe(500, 200, 500, 1000, 500)
            except Exception as e:
                print(e)
            time.sleep(self.ACTION_SLEEP_INTERVAL)

        else:
            print(f"Unknown action to be performed {operation_type}")

    def parse_element(self, element: str):
        result_element = {
            'resource-id': '',
            'class': '',
            'content-desc': '',
            'text': ''
        }

        attr_section = re.search(r'\((.*?)\), [^>]*>', element)
        if attr_section:
            attr_section = attr_section.group(1)
        else:
            return result_element

        patterns = {
            'resource-id': r'resource-id:([^,]*),?',
            'class': r'class:([^,]*),?',
            'content-desc': r'content-desc:([^,]*),?',
            'text': r'text:([^,]*)'
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, attr_section)
            if match is not None:
                result_element[key] = match.group(1).strip()

        print(f'result_element:{result_element}')
        print('================================================')
        return result_element

    def find_element(self, element, driver):
        xml = str(driver.page_source)
        id = element['resource-id']
        content_desc = element['content-desc']
        text = element['text']
        clazz = element['class']
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
                    candidate_elements[el] = 2

                elif content_desc == node_content_desc and content_desc != '':
                    ui_selector = f'new UiSelector().className("{clazz}").description("{content_desc}")'
                    el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
                    candidate_elements[el] = 2

                elif node_clazz != '':
                    ui_selector = f'new UiSelector().className("{clazz}")'
                    el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=ui_selector)
                    candidate_elements[el] = 3

        candidate_elements = sorted(candidate_elements.items(), key=lambda x: x[1], reverse=False)
        for candidate_element in candidate_elements:
            if candidate_element[0] is not None:
                el = candidate_element[0]
                break
        return el

    def get_child_to_parent_dict(self, root):

        res = {child_node: parent_node for parent_node in root.iter() for child_node in parent_node}
        return res

    def capture_current_screen_widgets(self, driver):
        widget_list = []
        xml_str = str(driver.page_source)
        root = ET.fromstring(xml_str)
        child_to_parent_dict = self.get_child_to_parent_dict(root)
        xml_node_list = []
        child_xml_node_list = []
        self.get_child_node_list(root, child_xml_node_list)
        xml_node_list.extend(child_xml_node_list)
        node_attrib_list = ['class', 'resource-id', 'content-desc', 'text', 'clickable']
        filtered_class_list = ['android.view.View', 'android.widget.RelativeLayout']
        for xml_node in xml_node_list:
            widget = {}
            for node_attrib in node_attrib_list:
                if node_attrib in xml_node.attrib:
                    widget[node_attrib] = xml_node.attrib[node_attrib]
                else:
                    widget[node_attrib] = ''
            # clickable transfer
            parent_node = child_to_parent_dict[xml_node]
            if parent_node.get('clickable') == 'true':
                widget['clickable'] = 'true'

            if widget['class'] in filtered_class_list:
                continue

            widget_list.append(widget)
            # replace the relationship
            parent_node = child_to_parent_dict[xml_node]
            child_to_parent_dict[str(widget)] = parent_node

        return widget_list, child_to_parent_dict

    def generate_combination_prompt(self, previous_intention_list, intention, before_screen_info, after_screen_info):
        task_prompt = f'Determine whether the current test intention has been achieved. Respond with "Yes" or "No".'
        intention_prompt = f'The previously realized intentions are as listed:{previous_intention_list}. The current intention to be realized is "{intention}".'
        gui_context_prompt = (f'The current GUI screen contains: {after_screen_info}.')
        combination_prompt = f'{task_prompt} {intention_prompt} {gui_context_prompt}'
        print(combination_prompt)
        return combination_prompt

    def prompt(self, messages, messages_list):
        response = openai.ChatCompletion.create(
            model=self.MODEL,
            messages=messages,
        )
        response_text = response['choices'][0]['message']['content'].strip()
        messages.append(self.construct_message("assistant", response_text))
        messages_list.append(messages)
        print(response_text)
        print("============================================================================================")
        return response_text

    def construct_message(self, role, content):
        return {"role": role, "content": content}

    def generate_screenshot_and_xml_path(self, path: Path, action_index):
        screenshot_before_path = path / f'{action_index}_a.png'
        screenshot_after_path = path / f'{action_index}_b.png'
        xml_before_path = path / f'{action_index}_a.xml'
        xml_after_path = path / f'{action_index}_b.xml'
        return screenshot_before_path, screenshot_after_path, xml_before_path, xml_after_path

    def record_screenshot_and_xml(self, screenshot_path: Path, xml_path: Path, driver):
        driver.get_screenshot_as_file(str(screenshot_path))
        xml_root_before = ET.fromstring(str(driver.page_source))
        xml_tree_before = ET.ElementTree(xml_root_before)
        xml_tree_before.write(xml_path)

    def get_interactive_widget_index_list(self, widget_list, child_to_parent_dict):
        interactive_widget_index_list = []
        for index, widget in enumerate(widget_list):
            if widget['clickable'] == 'true':
                for child_node in widget:
                    if child_node in widget_list:
                        interactive_widget_index_list.append(widget_list.index(child_node))
                interactive_widget_index_list.append(index)

        # handle sidebar
        sidebar_item_index_list = self.handle_sidebar(widget_list, child_to_parent_dict)
        interactive_widget_index_list.extend(sidebar_item_index_list)
        interactive_widget_list = [widget_list[x] for x in interactive_widget_index_list]
        print(interactive_widget_index_list)
        print(interactive_widget_list)
        return sorted(interactive_widget_index_list)

    def get_parent_to_child_dict(self, child_to_parent_dict):
        # {parent:[child_list]}
        parent_to_child_dict = {}
        for child_widget_str, parent_node in child_to_parent_dict.items():
            if parent_node not in parent_to_child_dict.keys():
                parent_to_child_dict[parent_node] = [child_widget_str]
            else:
                parent_to_child_dict[parent_node].append(child_widget_str)
        return parent_to_child_dict

    def handle_sidebar(self, widget_list, child_to_parent_dict):
        sidebar_item_index_list = []
        for index, widget in enumerate(widget_list):
            if widget['class'] != 'android.widget.TextView':
                continue
            parent_node = child_to_parent_dict[str(widget)]
            if parent_node is not None and 'class' in parent_node.attrib and (parent_node.attrib[
                                                                                  'class'] == 'android.widget.RelativeLayout' or
                                                                              parent_node.attrib[
                                                                                  'class'] == 'android.widget.LinearLayout'):
                parent_node = child_to_parent_dict[parent_node] if parent_node in child_to_parent_dict.keys() else None
                if parent_node is not None and 'class' in parent_node.attrib and parent_node.attrib[
                    'class'] == 'android.widget.LinearLayout':
                    parent_node = child_to_parent_dict[
                        parent_node] if parent_node in child_to_parent_dict.keys() else None
                    if parent_node is not None and 'class' in parent_node.attrib and parent_node.attrib[
                        'class'] == 'android.widget.ListView':
                        sidebar_item_index_list.append(index)
                        widget['clickable'] = True
        return sidebar_item_index_list

    def generate_exploration_prompt(self, intention, current_screen_widgets, child_to_parent_node_dict):
        task_prompt = ('I have some test intentions to execute on an Android app. I will provide each intention one at '
                       'a time, and I need your assistance to complete these tests by answering my questions.')

        interactive_widget_index_list = self.get_interactive_widget_index_list(current_screen_widgets,
                                                                               child_to_parent_node_dict)
        current_screen_prompt = f'The current screen contains some widgets, listed as: {current_screen_widgets}.'
        intention_prompt = (
            f'Determine the necessary operation to fulfill the test intention: {intention}. '
            'If the intention cannot be achieved in a single step, feel free to explore the application further. '
            'Available operations include: [click, long_click, back, input_and_enter, input, swipe_right, swipe_left, scroll_up, scroll_down]. '
            'If you are exploring the app to reach the intended functionality, please tag the step as "Explore"; otherwise, use "Exact". '
            f'When specifying a widget, use the index of the widget list to denote the widget. You have these indexes to choose from: {interactive_widget_index_list}. If you are not specifying a widget, use -1 to denote that. '
            'Please think step by step. '
            'Please limit your answer to one operation per response in the format <{Explore/Exact}, {Operation Type}, {Widget Index}, {InputValue/Empty}>. '
            'Example: <Explore, input, 3, YES>, <Exact, click, 0, Empty>, <Exact, back, -1, Empty>')
        exploration_prompt = f'{task_prompt} {current_screen_prompt} {intention_prompt}'
        return exploration_prompt

    def perform_intention(self, intention_list, driver, current_migration_task_trace, desired_caps):
        start_time = time.time()

        gpt_guidance_path = Path(self.GPT_GUIDANCE_PATH)
        current_migration_gpt_guidance_path = gpt_guidance_path / current_migration_task_trace.stem
        guidance_txt_path = current_migration_gpt_guidance_path / 'gpt.txt'
        time_txt_path = current_migration_gpt_guidance_path / 'time.txt'
        if not current_migration_gpt_guidance_path.exists():
            current_migration_gpt_guidance_path.mkdir()
        if not guidance_txt_path.exists():
            guidance_txt_path.touch()
        if not time_txt_path.exists():
            time_txt_path.touch()
        with open(guidance_txt_path, mode='r', encoding='utf-8') as f:
            guidance_list = f.readlines()
        exact_num = 0
        action_trace = []
        action_index = 0
        # store the messages interacting with LLM
        messages_list = []
        role_prompt = "You are an expert in Android."
        role_message = self.construct_message("system", role_prompt)

        # first perform the correct actions to avoid duplicated api use
        print(f'guidance_list: {guidance_list}')
        print('======================================================================')
        for guidance in guidance_list:
            screenshot_before_path, screenshot_after_path, xml_before_path, xml_after_path = self.generate_screenshot_and_xml_path(
                current_migration_task_trace, action_index)
            action_index += 1
            current_widget_list, _ = self.capture_current_screen_widgets(driver)
            self.record_screenshot_and_xml(screenshot_before_path, xml_before_path, driver)
            current_guidance = self.parse_and_perform_gpt_guidance(guidance, driver, action_trace, current_widget_list)
            self.record_screenshot_and_xml(screenshot_after_path, xml_after_path, driver)

            if 'Exact' in guidance:
                exact_num += 1

        # the guidance returned this time, corresponding to intention_list[exact_num:]
        additional_guidance_list = []
        recover_count = 0
        for intention_index, intention in enumerate(intention_list[exact_num:]):

            # exploration reasoning prompt
            current_screen_widgets, child_to_parent_node_dict = self.capture_current_screen_widgets(driver)
            exploration_prompt = self.generate_exploration_prompt(intention, current_screen_widgets,
                                                                  child_to_parent_node_dict)
            messages = [role_message, self.construct_message('user', exploration_prompt)]
            exploration_answer = self.prompt(messages, messages_list)
            exploration_count = EXPLORATION_LIMIT
            current_exploration_guidance_list = []
            app_package = get_current_package_name()
            while exploration_count != 0:
                screenshot_before_path, screenshot_after_path, xml_before_path, xml_after_path = self.generate_screenshot_and_xml_path(
                    current_migration_task_trace, action_index)
                action_index += 1
                before_screen_widget_list, _ = self.capture_current_screen_widgets(driver)
                self.record_screenshot_and_xml(screenshot_before_path, xml_before_path, driver)
                current_exploration_guidance = self.parse_and_perform_gpt_guidance(exploration_answer, driver,
                                                                                   action_trace,
                                                                                   before_screen_widget_list)
                messages.append(self.construct_message('assistant', current_exploration_guidance))
                current_exploration_guidance_list.append(current_exploration_guidance)
                after_screen_widget_list, child_to_parent_node_dict = self.capture_current_screen_widgets(driver)
                self.record_screenshot_and_xml(screenshot_after_path, xml_after_path, driver)

                # go out of the app, stop explore, kill intention, and recover
                current_package = get_current_package_name()
                if current_package == '':
                    current_package = app_package
                if app_package != current_package:
                    recover_count += 1
                    exploration_count = 0
                    break

                # thought analysis
                is_current_intention_complete = True if 'Exact' in exploration_answer else False
                if is_current_intention_complete:
                    break

                # ask for more steps for exploration to complete the test intention
                more_exploration_prompt = self.generate_more_exploration_prompt(before_screen_widget_list,
                                                                                after_screen_widget_list,
                                                                                child_to_parent_node_dict)
                messages.append(self.construct_message("user", more_exploration_prompt))
                exploration_answer = self.prompt(messages, messages_list)
                exploration_count -= 1

            # exploration exceed the limit number, recover the original steps
            if exploration_count == 0:
                recovered_guidance_list = guidance_list.copy()
                recovered_guidance_list.extend(additional_guidance_list)
                driver, action_index = self.recover_app(recovered_guidance_list, driver, desired_caps, action_index,
                                                        current_migration_task_trace, action_trace)
                recover_count += 1
                additional_guidance_list.extend(['<Skip>'])
                continue

            additional_guidance_list.extend(current_exploration_guidance_list)

        end_time = time.time()
        execution_time = end_time - start_time
        # minus sleep time
        execution_time -= (action_index * self.ACTION_SLEEP_INTERVAL)
        with open(time_txt_path, mode='w', encoding='utf-8') as f:
            f.write(str(execution_time))
        # store the additional guidance produced this time
        with open(guidance_txt_path, mode='a', encoding='utf-8') as f:
            for additional_guidance in additional_guidance_list:
                f.write(additional_guidance + '\n')
        return action_trace, messages_list

    def perform_gpt_guidance(self, driver, current_task_gpt_trace_folder_path):
        gpt_guidance_path = Path(self.GPT_GUIDANCE_PATH)
        current_task_gpt_guidance_path = gpt_guidance_path / current_task_gpt_trace_folder_path.stem
        guidance_txt_path = current_task_gpt_guidance_path / 'gpt.txt'
        with open(guidance_txt_path, mode='r', encoding='utf-8') as f:
            guidance_list = f.readlines()
        if current_task_gpt_trace_folder_path.exists():
            shutil.rmtree(current_task_gpt_trace_folder_path)
        current_task_gpt_trace_folder_path.mkdir()

        action_trace = []
        action_index = 0
        # perform all the guidance to get the action trace, skip will also be performed
        print(f'guidance_list: {guidance_list}')
        print('======================================================================')
        for index, guidance in enumerate(guidance_list):
            screenshot_before_path, screenshot_after_path, xml_before_path, xml_after_path = self.generate_screenshot_and_xml_path(
                current_task_gpt_trace_folder_path, action_index)
            action_index += 1
            current_widget_list, _ = self.capture_current_screen_widgets(driver)
            self.record_screenshot_and_xml(screenshot_before_path, xml_before_path, driver)
            # there are three types of guidance: exact, explore, skip, the number is the same as the original gui events
            current_guidance = self.parse_and_perform_gpt_guidance(guidance, driver, action_trace, current_widget_list)
            self.record_screenshot_and_xml(screenshot_after_path, xml_after_path, driver)

    def get_trace_xml_path_list(self, trace_folder_path):
        xml_before_path_list = []
        xml_after_path_list = []
        for file in trace_folder_path.glob('*'):
            if '_a.xml' in file.name:
                xml_before_path_list.append(file)
            if '_b.xml' in file.name:
                xml_after_path_list.append(file)
        xml_before_path_list = sorted(xml_before_path_list, key=lambda x: int(str(x.stem)[:-2]))
        xml_after_path_list = sorted(xml_after_path_list, key=lambda x: int(str(x.stem)[:-2]))
        return xml_before_path_list, xml_after_path_list

    def generate_oracle_from_gpt_trace(self, current_task_gpt_trace_folder_path, test_case,
                                       current_task_original_trace_folder_path, current_task_oracle_folder_path):

        old_xml_before_path_list, old_xml_after_path_list = self.get_trace_xml_path_list(
            current_task_original_trace_folder_path)
        new_xml_before_path_list, new_xml_after_path_list = self.get_trace_xml_path_list(
            current_task_gpt_trace_folder_path)

        role_prompt = "You are an expert in Android."
        role_message = self.construct_message("system", role_prompt)

        gpt_guidance_path = Path(self.GPT_GUIDANCE_PATH)
        current_task_gpt_guidance_path = gpt_guidance_path / current_task_gpt_trace_folder_path.stem
        guidance_txt_path = current_task_gpt_guidance_path / 'gpt.txt'
        with open(guidance_txt_path, mode='r', encoding='utf-8') as f:
            guidance_list = f.readlines()

        # store the messages interacting with LLM
        messages_list = []

        # perform all the guidance to get the action trace, skip will also be performed
        print(f'guidance_list: {guidance_list}')
        print('======================================================================')
        # store the executed gui event index of the guidance list
        # e.g. explore,explore,exact,explore,skip ---> [2,4]
        executed_gui_event_index_list = []
        for index, guidance in enumerate(guidance_list):
            if '<Exact' in guidance or '<Skip>' in guidance:
                executed_gui_event_index_list.append(index)

        start_time = time.time()
        oracle_list = []
        # recognize the position of oracle events, perform oracles
        gui_event_index = -1
        print(f'test_case: {test_case}')
        for index, event in enumerate(test_case):
            event_type = event['event_type']
            action = event['action']
            if event_type == 'gui' or event_type == 'SYS_EVENT':
                gui_event_index += 1
                continue
            if event_type != 'oracle':
                continue
            resource_id = event['resource-id']
            content_desc = event['content-desc']
            text = event['text']
            oracle_type, oracle_time, oracle_locator_type, oracle_locator = action

            # old trace contains oracle event while the gpt trace does not
            if index == 0:
                old_xml_path = old_xml_before_path_list[0]
                new_xml_path = new_xml_before_path_list[0]
            else:
                old_xml_path = old_xml_after_path_list[index]
                executed_gui_event_index = executed_gui_event_index_list[gui_event_index]
                new_xml_path = new_xml_after_path_list[executed_gui_event_index]
            oracle_prompt, new_widget_list = self.generate_oracle_prompt(old_xml_path, new_xml_path, action,
                                                                         resource_id, content_desc, text)
            print(f'new_widget_list: {new_widget_list}')

            oracle_answer = ''
            oracle = f'<{oracle_type},{oracle_time},{oracle_locator_type},{oracle_locator}>'
            # widget-relevant, the answer should be the index
            if oracle_prompt != '':
                messages = [role_message, self.construct_message('user', oracle_prompt)]
                oracle_answer = self.prompt(messages, messages_list)
                widget_index = self.parse_oracle_answer(oracle_answer)
                if widget_index != -1:
                    new_widget = new_widget_list[widget_index]
                else:
                    new_widget = ''
                # store in the oracle folder
                oracle = f'<{oracle_type},{oracle_time},{new_widget}>'

            oracle_list.append(oracle)

        end_time = time.time()
        execution_time = end_time - start_time
        time_txt_path = current_task_oracle_folder_path / 'time.txt'
        if not time_txt_path.exists():
            time_txt_path.touch()
        with open(time_txt_path, mode='w', encoding='utf-8') as f:
            f.write(str(execution_time))

        return oracle_list, messages_list

    def parse_oracle_answer(self, oracle_answer):
        if '<index:-1>' in oracle_answer or '<index:>' in oracle_answer:
            return -1
        pattern = r'<index:\d+>'
        oracle_answer = re.search(pattern, oracle_answer).group().replace('<', '').replace('>', '')
        return int(oracle_answer.split(':')[1].strip())

    def generate_oracle_prompt(self, old_xml_path, new_xml_path, action, resource_id, content_desc, text):
        oracle_type, oracle_time, oracle_locator_type, oracle_locator = action
        # Handling text-related oracles directly
        if oracle_type in ['wait_until_text_presence', 'wait_until_text_invisible']:
            return '', []

        # Task description for transferring test assertions between apps
        task_prompt = 'Assist in transferring a test assertion from one app to another based on the provided details.'

        # Describing the original oracle and task for element presence
        old_oracle_prompt = 'Original assertion checks for the presence of a GUI element.'
        old_widget_list = self.get_widget_list_from_xml(old_xml_path)
        new_widget_list = self.get_widget_list_from_xml(new_xml_path)

        # Constructing the prompts for old and new elements
        old_element_prompt = f'This original element is identified by <resource-id:{resource_id}, content-desc:{content_desc}, text:{text}> within a GUI containing: {old_widget_list}'
        new_question_prompt = f'Identify a corresponding element in the new GUI that fulfills a similar role. The new GUI contains: {new_widget_list}'

        # Instruction for the expected response format
        answer_prompt = "Let's think step by step. Provide the index of the matching element from the new widget list. The index starts from 0. If there is no matching widget, return -1. The format should be <index:>, e.g. <index:0>, <index:-1>"

        # Combining all parts to form the complete prompt
        prompt = f"{task_prompt} {old_oracle_prompt} {old_element_prompt} {new_question_prompt} {answer_prompt}"
        print(prompt)
        print('================================================================================')

        return prompt, new_widget_list

    def get_widget_list_from_xml(self, xml_path):
        widget_list = []
        tree = ET.ElementTree(file=xml_path)
        root = tree.getroot()
        xml_node_list = []
        child_xml_node_list = []
        self.get_child_node_list(root, child_xml_node_list)
        xml_node_list.extend(child_xml_node_list)
        node_attrib_list = ['class', 'resource-id', 'content-desc', 'text']
        for xml_node in xml_node_list:
            widget = {}
            for node_attrib in node_attrib_list:
                if node_attrib in xml_node.attrib:
                    widget[node_attrib] = xml_node.attrib[node_attrib]
                else:
                    widget[node_attrib] = ''
            if self.is_empty_widget(widget):
                continue
            widget_list.append(widget)

        # add index into the list
        for index, widget in enumerate(widget_list):
            widget['index'] = index
        return widget_list

    def is_empty_widget(self, widget):
        class_list = ['android.widget.ImageButton']
        if widget['resource-id'] == widget['text'] == widget['content-desc'] == '' and widget[
            'class'] not in class_list:
            return True
        return False

    def connect_device(self, desired_caps):
        appium_server_url = 'http://localhost:4723'
        driver = webdriver.Remote(appium_server_url, options=UiAutomator2Options().load_capabilities(desired_caps))
        time.sleep(15)
        return driver

    def hide_keyboard(self, driver):
        if driver.is_keyboard_shown:
            try:
                driver.hide_keyboard()
            except WebDriverException:
                pass

    def recover_app(self, recovered_guidance_list, driver, desired_caps, action_index, current_migration_task_trace,
                    action_trace):
        self.hide_keyboard(driver)
        driver.quit()
        time.sleep(1)
        print(recovered_guidance_list)
        new_driver = self.connect_device(desired_caps)
        for guidance in recovered_guidance_list:
            screenshot_before_path, screenshot_after_path, xml_before_path, xml_after_path = self.generate_screenshot_and_xml_path(
                current_migration_task_trace, action_index)
            action_index += 1
            self.record_screenshot_and_xml(screenshot_before_path, xml_before_path, new_driver)
            current_widget_list, _ = self.capture_current_screen_widgets(new_driver)
            current_guidance = self.parse_and_perform_gpt_guidance(guidance, new_driver, action_trace,
                                                                   current_widget_list)
            self.record_screenshot_and_xml(screenshot_after_path, xml_after_path, new_driver)
        return new_driver, action_index

    def generate_more_exploration_prompt(self, before_screen_info, after_screen_info, child_to_parent_node_dict):
        interactive_widget_index_list = self.get_interactive_widget_index_list(after_screen_info,
                                                                               child_to_parent_node_dict)

        more_prompt = (
            f'Before the operation, the GUI screen displayed: {before_screen_info}. After the operation, '
            f'the current screen displays: {after_screen_info}. Since your are exploring the app, please give '
            'me one more operation in the format <{Explore/Exact}, {Operation Type}, {Widget Index}, {InputValue/Empty}>. '
            'Please think step by step. '
            f'For widgets, you have these indexes to choose from: {interactive_widget_index_list}.')
        return more_prompt

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

    def generate_gui_script(self, action_trace):
        gui_event_script_list = []

        for i, test_action in enumerate(action_trace):
            event_type = test_action['event_type']
            action = test_action['action']
            action_name = action[0]

            if event_type == 'oracle':
                continue

            elif event_type == 'gui':
                id = test_action['resource-id']
                content_desc = test_action['content-desc']
                text = test_action['text']
                clazz = test_action['class']

                # relevant information
                if len(action) == 1:
                    action_info = f'operation type: <{action_name}>'
                else:
                    action_info = f'operation type: <{action_name}>, input value: <{action[1]}>'
                widget_info = f'target widget: (id:<{id}>,content-desc:<{content_desc}>,text:<{text}>,class:<{clazz}>)'
                gui_event_script = f'{action_info}, {widget_info}'
                gui_event_script_list.append(gui_event_script)

            elif event_type == 'SYS_EVENT':
                action_info = f'operation type: <{action_name}>'
                gui_event_script = f'{action_info}'
                gui_event_script_list.append(gui_event_script)

        return gui_event_script_list

    def generate_test_intention(self, action_trace, screen_before_path_list, screen_after_path_list):
        start_time = time.time()
        task_prompt = ('I have an execution trace of a test script for an Android app. Your task is to analyze the '
                       'trace and identify the test intention behind each test action of the trace. For each action, your response should include any '
                       'specific input values associated with it if necessary.')
        requirement_prompt = (
            'I will give the execution trace action by action. Please think step by step. You just need to give me the test '
            'intention by filling the {Your answer} in <Intent: {Your answer}>.')
        example_prompt_1 = 'e.g. <Intent: input (www.google.com) into the search bar and navigate to the website>'
        example_prompt_2 = '<Intent: click the "Sign In" button to log in>'
        example_prompt_3 = '<Intent: navigate from the current web page back to the previous web page>'
        gui_event_prompt_list = self.generate_gui_event_prompt(action_trace, screen_before_path_list,
                                                               screen_after_path_list)

        print(f'{task_prompt} {requirement_prompt}')

        for gui_event_prompt in gui_event_prompt_list:
            print()
            print('=============================================================================')
            print(gui_event_prompt)
            print('=============================================================================')
            print()

        responses = []
        role_message = self.construct_message('system', "You are an expert in Android.")
        messages = [role_message]
        messages.append(self.construct_message('user',
                                               f'{task_prompt} {requirement_prompt} {example_prompt_1} {example_prompt_2} {example_prompt_3}'))

        for gui_event_prompt in alive_it(gui_event_prompt_list, force_tty=True, total=len(gui_event_prompt_list),
                                         title='GUI Event Prompt'):
            messages.append(self.construct_message('user', f'{gui_event_prompt}'))
            response = openai.ChatCompletion.create(
                model=self.MODEL,
                messages=messages,
            )
            response_text = response['choices'][0]['message']['content'].strip()
            responses.append(response_text)
            messages.append({"role": "assistant", "content": response_text})
        end_time = time.time()
        execution_time = end_time - start_time
        return responses, execution_time
