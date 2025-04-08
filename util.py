import subprocess


def run_cmd(command):
    res = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    return res.stdout


def get_current_package_name():
    raw_content = run_cmd('adb shell dumpsys activity | findstr "mFocusedActivity"')
    print(raw_content)
    try:
        result = raw_content.strip().split(': ')[1].split(' ')[2].split('/')[0]
    except:
        result = ''
    return result
