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
from os.path import join

from adapt.intent import IntentBuilder
from mycroft import MYCROFT_ROOT_PATH
from mycroft.configuration import ConfigurationManager
from mycroft.skills.core import MycroftSkill
from mycroft.util.log import getLogger

__author__ = 'augustnmonteiro2'

logger = getLogger(__name__)

installer_config = ConfigurationManager.instance().get("SkillInstallerSkill")
BIN = installer_config.get("path", join(MYCROFT_ROOT_PATH, 'msm', 'msm'))


class SkillInstallerSkill(MycroftSkill):
    def __init__(self):
        super(SkillInstallerSkill, self).__init__(name="SkillInstallerSkill")

    def initialize(self):
        install = IntentBuilder("InstallIntent"). \
            require("InstallKeyword").build()
        self.register_intent(install, self.install)

    def install(self, message):
        utterance = message.data.get('utterance').lower()
        skill = utterance.replace(message.data.get('InstallKeyword'), '')
        self.speak_dialog("installing")

        cmd = BIN + " install " + skill.strip().replace(" ", "-")
        installer = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE)
        text = installer.stdout.read().splitlines()
        installer.communicate()

        # Check return code or error code reported in text
        if installer.returncode != 0 or len(text[-1].split('Err')) == 2:
            err = installer.returncode or text[-1].split('Err')[1]
            self.report_error(skill, text, int(err))
        elif 'has been installed' in text[-1]:
            self.speak_dialog("installed", data={'skill': skill})

    def report_error(self, skill, text, err):
        """ parse error text and report error to user """

        if text[2] == 'Your search has multiple choices':
            self.speak_dialog("choose",
                              data={'skills': ", ".join(stdout[5:-1])})
        elif "skill was not found" in text[2] or skill == "":
            self.speak_dialog("not.found", data={'skill': skill})
        else:
            self.speak_dialog("other.error",
                    data={'error': err, 'skill': skill})

    def stop(self):
        pass


def create_skill():
    return SkillInstallerSkill()
