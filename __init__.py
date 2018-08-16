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
from contextlib import contextmanager
from random import shuffle

from msm import SkillNotFound, SkillRequirementsException, \
    PipRequirementsException, SystemRequirementsException, CloneException, \
    GitException, AlreadyRemoved, AlreadyInstalled, MsmException, SkillEntry, \
    MultipleSkillMatches, MycroftSkillsManager
from mycroft import intent_file_handler, MycroftSkill
from mycroft.skills.main import SkillManager


class SkillInstallerSkill(MycroftSkill):
    def __init__(self):
        super(SkillInstallerSkill, self).__init__()
        try:
            self.msm = SkillManager.create_msm()
        except AttributeError:
            self.msm = MycroftSkillsManager()
        self.yes_words = self.install_word = self.remove_word = None

    def initialize(self):
        self.settings.set_changed_callback(self.on_web_settings_change)
        self.install_word, self.remove_word = self.translate_list('action')
        self.yes_words = set(self.translate_list('yes'))

    def load_skills_data(self):
        """Compatibility wrapper. Remove in 18.08"""
        return getattr(SkillManager, 'load_skills_data', lambda: {})()

    def write_skills_data(self, skills_data):
        """Compatibility wrapper. Remove in 18.08"""
        getattr(SkillManager, 'write_skills_data', lambda x: None)(skills_data)

    @intent_file_handler('install.intent')
    def install(self, message):
        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], False)
            skills_data = self.load_skills_data()
            skill_data = skills_data.setdefault(skill.name, {})
            was_beta = skill_data.get('beta')

            if not was_beta and skill.is_local:
                raise AlreadyInstalled(skill.name)

            if skill.is_local:
                dialog = 'install.reinstall.confirm'
            else:
                dialog = 'install.confirm'

            if not self.confirm_skill_action(skill, dialog):
                return

            skill_data['beta'] = False
            skill_data['manual_install'] = True
            self.write_skills_data(skills_data)

            if skill.is_local:
                skill.remove()
                skill.install()
            else:
                skill.install()

            self.speak_dialog('install.complete', dict(skill=skill.name))

    @intent_file_handler('install.beta.intent')
    def install_beta(self, message):
        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], False)
            skill.sha = None
            skills_data = self.load_skills_data()
            skill_data = skills_data.setdefault(skill.name, {})
            was_beta = skill_data.get('beta')

            if was_beta and skill.is_local:
                self.speak_dialog('error.already.beta', dict(skill=skill.name))
                return

            if skill.is_local:
                dialog = 'install.beta.upgrade.confirm'
            else:
                dialog = 'install.beta.confirm'

            if not self.confirm_skill_action(skill, dialog):
                return

            skill_data['beta'] = True
            skill_data['manual_install'] = True
            self.write_skills_data(skills_data)

            if skill.is_local:
                skill.update()
            else:
                skill.install()

            self.speak_dialog('install.beta.complete', dict(skill=skill.name))

    @intent_file_handler('remove.intent')
    def remove(self, message):
        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], True)
            if not skill.is_local:
                raise AlreadyRemoved(skill.name)

            if not self.confirm_skill_action(skill, 'remove.confirm'):
                return

            skill.remove()
            skills_data = self.load_skills_data()
            if skill.name in skills_data:
                del skills_data[skill.name]
            self.write_skills_data(skills_data)
            self.speak_dialog('remove.complete', dict(skill=skill.name))

    @intent_file_handler('list.skills.intent')
    def handle_list_skills(self, message):
        skills = [skill for skill in self.msm.list() if not skill.is_local]
        shuffle(skills)
        skills = ', '.join(skill.name for skill in skills[:4])
        self.speak_dialog('some.available.skills', dict(skills=skills))

    @intent_file_handler('install.custom.intent')
    def install_custom(self, message):
        link = self.settings.get('installer_link')
        if link:
            name = SkillEntry.extract_repo_name(link)
            with self.handle_msm_errors(name, self.install_word):
                self.msm.install(link)

    @contextmanager
    def handle_msm_errors(self, skill, action):
        try:
            yield
        except MsmException as e:
            error_dialog = {
                SkillNotFound: 'error.not.found',
                SkillRequirementsException: 'error.skill.requirements',
                PipRequirementsException: 'error.pip.requirements',
                SystemRequirementsException: 'error.system.requirements',
                CloneException: 'error.filesystem',
                GitException: 'error.filesystem',
                AlreadyRemoved: 'error.already.removed',
                AlreadyInstalled: 'error.already.installed',
                MultipleSkillMatches: 'error.multiple.skills'
            }.get(type(e), 'error.other')
            data = {'skill': skill, 'action': action}
            if isinstance(e, (SkillNotFound, AlreadyRemoved,
                              AlreadyInstalled)):
                data['skill'] = str(e)
            self.speak_dialog(error_dialog, data)
            self.log.error('Msm failed: ' + repr(e))
        except StopIteration:
            self.speak_dialog('cancelled')

    def on_web_settings_change(self):
        self.log.info('Installer Skill web settings have changed')
        s = self.settings
        link = s.get('installer_link')
        prev_link = s.get('previous_link')
        auto_install = s.get('auto_install') == 'true'

        if link and prev_link != link and auto_install:
            s['previous_link'] = link

            action = self.translate_list('action')[0]
            name = SkillEntry.extract_repo_name(link)
            with self.handle_msm_errors(name, action):
                self.msm.install(link)

    def confirm_skill_action(self, skill, confirm_dialog):
        response = self.get_response(
            confirm_dialog, num_retries=0,
            data={'skill': skill.name, 'author': skill.author}
        )

        if response and self.yes_words & set(response.split()):
            return True
        else:
            self.speak_dialog('cancelled')
            return False

    def find_skill(self, param, local):
        """Find a skill, asking if multiple are found"""
        try:
            return self.msm.find_skill(param)
        except MultipleSkillMatches as e:
            skills = [i for i in e.skills if i.is_local == local]
            or_word = self.translate('or')
            if len(skills) >= 10:
                self.speak_dialog('error.too.many.skills')
                raise StopIteration
            names = [skill.name for skill in skills]
            response = self.get_response(
                'choose.skill', num_retries=0,
                data={'skills': ' '.join([
                    ', '.join(names[:-1]), or_word, names[-1]
                ])},
            )
            if not response:
                raise StopIteration
            return self.msm.find_skill(response, skills=e.skills)

    def stop(self):
        pass


def create_skill():
    return SkillInstallerSkill()
