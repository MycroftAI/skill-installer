# Copyright 2016 Mycroft AI, Inc.
#
# This file is part of Mycroft Core.
#
# Mycroft Core is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Mycroft Core is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Mycroft Core.  If not, see <http://www.gnu.org/licenses/>.
import subprocess
import re
from os.path import join

from adapt.intent import IntentBuilder
from mycroft import MYCROFT_ROOT_PATH
from mycroft.configuration import ConfigurationManager
from mycroft.skills.core import MycroftSkill, intent_handler

__author__ = 'augustnmonteiro2'


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
            # TODO: Speak the skill name?  Parse for "Installed: (.*)"
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

    @intent_handler(IntentBuilder("GithubIntent").require("Github"))
    def install(self, message):
        utterance = message.data.get('utterance').lower()
        url = message.data["URL"]
        self.speak_dialog("installing")

        # Invoke MSM to perform installation
        try:
            cmd = ' '.join([BIN, 'install' + url)
            output = subprocess.check_output(cmd, shell=True)
            self.log.info("MSM output: " + str(output))
            rc = 0
        except subprocess.CalledProcessError, e:
            output = e.output
            rc = e.returncode
        if rc == 0:
            # Success!
            # TODO: Speak the skill name?  Parse for "Installed: (.*)"
            self.speak_dialog("installed", data={'skill': url})
        elif rc == 20:
            # Already installed
            self.speak_dialog("already.installed", data={'skill': url})
        elif rc == 202:
            # Not found
            self.speak_dialog("not.found", data={'skill': url})
        else:
            # Other installation error, just read code
            self.speak_dialog("installation.error", data={'skill': url,
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
            # TODO: Speak the skill name?  Parse for "Removed: (.*)"
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
