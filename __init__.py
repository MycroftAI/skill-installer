# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import subprocess
import re
from os.path import join

from adapt.intent import IntentBuilder
from mycroft import MYCROFT_ROOT_PATH
from mycroft.configuration import ConfigurationManager
from mycroft.skills.core import MycroftSkill, intent_handler


installer_config = ConfigurationManager.instance().get("SkillInstallerSkill")
BIN = installer_config.get("path", join(MYCROFT_ROOT_PATH, 'msm', 'msm'))


class SkillInstallerSkill(MycroftSkill):
    def __init__(self):
        super(SkillInstallerSkill, self).__init__(name="SkillInstallerSkill")

    @intent_handler(IntentBuilder("InstallIntent").require("Install"))
    def install(self, message):
        utterance = message.data.get('utterance').lower()
        name = utterance.replace(message.data.get('Install'), '')
        self.speak_dialog("installing")

        # Invoke MSM to perform installation
        try:
            cmd = ' '.join([BIN, 'install', '"' + name.strip() + '"'])
            output = subprocess.check_output(cmd, shell=True)
            self.log.info("MSM output: " + str(output))
            rc = 0
        except subprocess.CalledProcessError, e:
            output = e.output
            rc = e.returncode

        if rc == 0:
            # Success!
            self.speak_dialog("installed", data={'skill': name})
        elif rc == 20:
            # Already installed
            self.speak_dialog("already.installed", data={'skill': name})
        elif rc == 201:
            # Multiple matches found

            # A line of dashes starts and ends the list of skills in output
            pat = re.compile("----------$(.*)^----------",
                             re.DOTALL | re.MULTILINE)
            match = pat.search(output)
            if match:
                skills = match.group(1)
            else:
                skills = ""

            # read the list for followup
            self.speak_dialog("choose", data={'skills': ", ".join(skills)})
        elif rc == 202:
            # Not found
            self.speak_dialog("not.found", data={'skill': name})
        else:
            # Other installation error, just read code
            self.speak_dialog("installation.error", data={'skill': name,
                                                          'error': rc})

    @intent_handler(IntentBuilder("UninstallIntent").require("Uninstall"))
    def uninstall(self, message):
        utterance = message.data.get('utterance').lower()
        name = utterance.replace(message.data.get('Uninstall'), '')
        self.speak_dialog("removing")

        # Invoke MSM to perform removal
        try:
            cmd = ' '.join([BIN, 'remove', '"' + name.strip() + '"'])
            output = subprocess.check_output(cmd, shell=True)
            self.log.info("MSM output: " + str(output))
            rc = 0
        except subprocess.CalledProcessError, e:
            output = e.output
            rc = e.returncode

        if rc == 0:
            # Success, removed!
            self.speak_dialog("removed", data={'skill': name})
        elif rc == 253:
            # Already installed
            self.speak_dialog("remove.not.found", data={'skill': name})
        elif rc == 251:
            # Multiple matches found

            # A line of dashes starts and ends the list of skills in output
            pat = re.compile("----------$(.*)^----------",
                             re.DOTALL | re.MULTILINE)
            match = pat.search(output)
            if match:
                skills = match.group(1)
            else:
                skills = ""

            # read the list for followup
            self.speak_dialog("choose", data={'skills': ", ".join(skills)})
        else:
            # Other removal error, just read code
            self.speak_dialog("removal.error", data={'skill': name,
                                                     'error': rc})


def create_skill():
    return SkillInstallerSkill()
