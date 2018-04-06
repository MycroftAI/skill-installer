#  Copyright 2017 Mycroft AI Inc.
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
import subprocess
from difflib import SequenceMatcher
from random import shuffle
from subprocess import check_output
import re
from os.path import join, isfile

from adapt.intent import IntentBuilder
from mycroft import MYCROFT_ROOT_PATH
from mycroft.configuration import ConfigurationManager
try:  # backwards compatibility
    from mycroft.skills.core import MycroftSkill, intent_handler
except ImportError:
    from mycroft.skills.core import MycroftSkill
from logging import getLogger


installer_config = ConfigurationManager.instance().get("SkillInstallerSkill")
BIN = installer_config.get("path", join(MYCROFT_ROOT_PATH, 'msm', 'msm'))


# TODO: backwards compatibility tags are there for devices
# who have not done a platform patch It can be removed once comfortable
# devices are updated to be 0.9.1+
class SkillInstallerSkill(MycroftSkill):
    # Words STT incorrectly transcribes "skill" to
    # TODO:18.02 Support translations
    SKILL_WORDS = ['scale', 'steel']
    COMMON_TOKENS = ['skill', 'fallback', 'mycroft']
    ERROR_DIALOGS = {
        5: 'system.error',  # missing.virtualenv
        20: 'already.installed',
        102: 'filesystem.error',  # could.not.access.directory
        111: 'network.error',  # could.not.download.list
        112: 'network.error',  # could.not.download.list
        120: 'system.error',  # missing.virtualenv
        121: 'installation.error',  # python.dependency.installation.failed
        122: 'installation.error',  # dependency.installation.failed
        123: 'filesystem.error',  # could.not.change.permissions
        202: 'not.found',  # skill.not.in.repo
        252: 'not.found',  # skill.not.in.repo
        249: 'filesystem.error',  # remove.permission.denied
        253: 'remove.not.found'
    }

    def __init__(self):
        super(SkillInstallerSkill, self).__init__(name="SkillInstallerSkill")
        self.ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
        # TODO: Can be removed once all units are updated
        # This is for backwards compatibility
        self.log = getLogger()

    def initialize(self):
        installer = \
            IntentBuilder("InstallIntent").require("Install").build()
        self.register_intent(installer, self.install)

        try:  # backwards capatability
            self.register_intent_file('uninstall.intent', self.uninstall)
            self.register_intent_file(
                'list.skills.intent', self.handle_list_skills)
            self.register_intent_file(
                'install.custom.intent', self.install_custom)
            self.settings.set_changed_callback(self._on_web_settings_changed)
        except AttributeError:
            self.log.exception('Running outdated version')

    def __translate_list(self, list_name):
        try:  # backwards capatability
            return self.translate_list(list_name)
        except AttributeError:
            list_file = join(self.vocab_dir, 'action.list')
            if isfile(list_file):
                with open(list_file) as f:
                    return f.read().split('\n')
            self.log.error('Missing list: ' + list_file)
            return ['<invalid>']

    def get_skill_list(self):
        """Finds the names of all available"""
        return [
            i.strip() for i in
            self.ansi_escape.sub('', check_output([BIN, 'list'])).split('\n')
        ]

    def search_for_skill(self, search, skill_list):
        """Returns list of possible skills"""

        def extract_tokens(s, tokens):
            s = s.lower()
            extracted = []
            for token in tokens:
                extracted += token * s.count(token)
                s = s.replace(token, '')
            s = ' '.join(i for i in s.split(' ') if i)
            return s, extracted

        def compare_seq(a, b):
            return SequenceMatcher(a=a, b=b).ratio()

        for close_word in self.SKILL_WORDS:
            search = search.replace(close_word, 'skill')
        search, search_common = extract_tokens(search, self.COMMON_TOKENS)
        search_tokens = [i for i in search.split(' ') if i]

        confidences = {}
        for skill in skill_list:
            skill = skill.replace('[installed]', '').strip()
            if not skill:
                continue
            full_name = skill
            skill = skill.replace('-', ' ')
            skill, skill_common = extract_tokens(skill, self.COMMON_TOKENS)

            char_conf = compare_seq(skill, search)
            word_conf = compare_seq(skill.split(' '), search_tokens)
            common_conf = compare_seq(skill_common, search_common)
            conf = (0.45 * char_conf + 0.45 * word_conf + 0.1 * common_conf)

            confidences[full_name] = conf

        best_skill, best_conf = max(confidences.items(), key=lambda x: x[1])
        best_skills = \
            [s for s, c in confidences.items() if c > best_conf - 0.1]

        self.log.info('Highest Confidence Skill: ' + best_skill)
        self.log.info('Highest Confidence: ' + str(best_conf))

        if best_conf < 0.4:
            return []
        elif best_conf == 1.0:
            return [best_skill]
        else:
            return best_skills

    def msm_install(self, skill, action, from_web_settings=False):
        self.speak_dialog("installing")
        try:
            output = check_output([BIN, 'install', skill])
        except subprocess.CalledProcessError as e:
            self.log.error(
                "MSM returned " + str(e.returncode) + ": " + e.output)
            dialog = self.ERROR_DIALOGS.get(e.returncode, "installation.error")
            if from_web_settings:
                skill = self.get_custom_skill_name(skill)
            self.speak_dialog(dialog, dict(skill=skill, action=action,
                                           error=e.returncode))
        else:
            if from_web_settings:
                skill = self.get_custom_skill_name(skill)
            self.log.info("MSM output: " + str(output))
            self.speak_dialog("installed", data={'skill': skill})

    def install(self, message):
        try:  # backwards compatibility
            action = self.__translate_list('action')[0]
        except AttributeError:
            action = 'installing'
        utterance = message.data['utterance'].lower()
        search = utterance.replace(message.data['Install'], '').strip()
        try:
            skills = self.search_for_skill(search, self.get_skill_list())
        except subprocess.CalledProcessError as e:
            self.log.error(
                "MSM returned " + str(e.returncode) + ": " + e.output)
            self.speak_dialog("skill.list.failed")
            return

        if not skills:
            self.speak_dialog("not.found", dict(skill=search, action=action))
        elif len(skills) == 1:
            skill = skills[0]
            try:
                response = self.get_response(
                    'install.confirmation', dict(skill=skill))
                yes_set = set(self.__translate_list('yes'))
                if response and yes_set & set(response.split()):
                    self.msm_install(skill, action)
                else:
                    self.speak_dialog(
                        'decline.install', data=dict(skill=skill))
            except AttributeError:
                self.log.info('Running an older version')

                self.msm_install(skill, action)
        elif len(skills) < 8:
            try:  # for backwards compatibility
                # number generation is currently in english
                l = [
                    str(i + 1) + ": " + skill
                    for i, skill in enumerate(skills)
                ]

                joined_list = ', '.join(l[:-1]) + " or " + l[-1]
                # TODO:18.02 Support translations
                # joined_list = ', '.join(l[:-1]) + " or " + \
                #       self.translate("or") + " " + l[-1]

                response = self.get_response(
                    "choose",
                    data={
                        'action': 'install',
                        'skills': joined_list},
                    num_retries=1
                )
                if not response:
                    return

                for i, skill in enumerate(skills):
                    self.log.info("REsponse: " + str(response))
                    if str(i + 1) in response:
                        self.msm_install(skill, action)
                        break
                else:
                    best_match = (None, float("-inf"))
                    for skill in skills:
                        conf = SequenceMatcher(a=skill, b=response).ratio()
                        if conf > 0.5 and conf > best_match[1]:
                            best_match = (skill, conf)
                            self.log.info(best_match)
                    if best_match[0]:
                        self.msm_install(best_match[0], action)
                    else:
                        self.speak_dialog(
                            'decline.install', data=dict(skill='them'))
            except AttributeError:
                self.speak_dialog('too.many.matches')
        else:
            self.speak_dialog('too.many.matches')

    def handle_list_skills(self, message):
        skill_list = self.get_skill_list()
        skill_list = [
            skill for skill in skill_list
            if '[installed]' not in skill
        ]
        shuffle(skill_list)
        skills = ', '.join(skill_list[:4])
        self.speak_dialog('some.available.skills', dict(skills=skills))

    def msm_uninstall(self, skill, action):
        self.speak_dialog("removing")
        try:
            output = check_output([BIN, 'remove', skill])
        except subprocess.CalledProcessError as e:
            self.log.error(
                "MSM returned " + str(e.returncode) + ": " + e.output)
            dialog = \
                self.ERROR_DIALOGS.get(e.returncode, "removal.error")
            self.speak_dialog(dialog, data=dict(
                skill=skill, action=action, error=e.returncode))
        else:
            self.log.info("MSM output: " + str(output))
            self.speak_dialog("removed", data={'skill': skill})

    def uninstall(self, message):
        if 'skill' not in message.data:
            self.speak_dialog('remove.not.found.no.skill')
            return

        action = self.__translate_list('action')[1]
        search = message.data['skill']

        # TODO: Only look for skills that are already installed
        self.log.info(self.get_skill_list())
        skill_list = [
            i.replace('[installed]', "")
            for i in self.get_skill_list() if '[installed]' in i
        ]
        self.log.info(skill_list)
        skills = self.search_for_skill(search, self.get_skill_list())

        if not skills:
            self.speak_dialog("remove.not.found", dict(skill=search))
        elif len(skills) == 1:
            skill = skills[0]
            # Invoke MSM to perform removal
            response = self.get_response(
                'uninstall.confirmation',
                dict(skill=skill), num_retries=0
            )
            yes_set = set(self.__translate_list('yes'))
            if response and yes_set & set(response.split()):
                self.msm_uninstall(skill, action)
            else:
                self.speak_dialog('decline.removal', data={'skill': skill})
        elif len(skills) > 1:
            # number generation is currently in english
            l = [
                str(i + 1) + ", " + skill
                for i, skill in enumerate(skills)
            ]

            joined_list = ', '.join(l[:-1]) + " or " + l[-1]
            # TODO:18.02 Support translations
            # joined_list = ', '.join(l[:-1]) + " or " + \
            #       self.translate("or") + " " + l[-1]

            response = self.get_response(
                "choose",
                data={
                    'action': 'uninstall',
                    'skills': joined_list
                },
                num_retries=0
            )
            if not response:
                return

            for i, skill in enumerate(skills):
                if str(i + 1) in response:
                    self.msm_uninstall(skill, action)
                    break
            else:
                best_match = (None, float("-inf"))
                for skill in skills:
                    conf = SequenceMatcher(a=skill, b=response).ratio()
                    if conf > 0.5 and conf > best_match[1]:
                        best_match = (skill, conf)
                        self.log.info(best_match)
                if best_match[0]:
                    self.msm_uninstall(best_match[0], action)
                else:
                    self.speak_dialog(
                        'decline.removal', data=dict(skill='them'))

    def get_custom_skill_name(self, url):
        forward_slash_count = 0
        skill_name = []
        self.log.info(url)
        for letter in url.decode("utf-8"):
            if forward_slash_count >= 4:
                skill_name.append(letter)
            if letter == '/':
                forward_slash_count += 1
        return "".join(skill_name[:-4])

    def install_custom(self, message):
        action = self.__translate_list('action')[0]
        link = self.settings.get('installer_link')
        if link:
            self.msm_install(link, action, from_web_settings=True)

    def _on_web_settings_changed(self):
        self.log.info('onchaged callback')
        previous_link = self.settings.get('previous_link')
        new_link = self.settings.get('installer_link')
        auto_install = \
            True if self.settings.get('auto_install') == 'true' else False

        def install():
            action = self.__translate_list('action')[0]
            self.msm_install(new_link, action, from_web_settings=True)
            self.settings['previous_link'] = new_link

        if new_link and auto_install:
            if previous_link is None:
                install()
            elif previous_link != new_link:
                install()


def create_skill():
    return SkillInstallerSkill()
