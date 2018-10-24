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
from mycroft.skills.skill_manager import SkillManager


class SkillInstallerSkill(MycroftSkill):
    def __init__(self):
        super().__init__()
        self.msm = SkillManager.create_msm()
        self.install_word = self.remove_word = None

    def initialize(self):
        self.settings.set_changed_callback(self.on_web_settings_change)
        self.install_word, self.remove_word = self.translate_list('action')

    @intent_file_handler('install.intent')
    def install(self, message):
        # Failsafe if padatious matches without skill entity.
        if not message.data.get('skill'):
            return self.handle_list_skills(message)

        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], False)
            skills_data = SkillManager.load_skills_data()
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
            SkillManager.write_skills_data(skills_data)

            if skill.is_local:
                skill.remove()
                skill.install()
            else:
                skill.install()

            self.speak_dialog('install.complete',
                              dict(skill=self.clean_name(skill)))

    @intent_file_handler('install.beta.intent')
    def install_beta(self, message):
        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], False)
            skill.sha = None
            skills_data = SkillManager.load_skills_data()
            skill_data = skills_data.setdefault(skill.name, {})
            was_beta = skill_data.get('beta')

            if was_beta and skill.is_local:
                self.speak_dialog('error.already.beta',
                                  dict(skill=self.clean_name(skill)))
                return

            if skill.is_local:
                dialog = 'install.beta.upgrade.confirm'
            else:
                dialog = 'install.beta.confirm'

            if not self.confirm_skill_action(skill, dialog):
                return

            skill_data['beta'] = True
            skill_data['manual_install'] = True
            SkillManager.write_skills_data(skills_data)

            if skill.is_local:
                skill.update()
            else:
                skill.install()

            self.speak_dialog('install.beta.complete',
                              dict(skill=self.clean_name(skill)))

    @intent_file_handler('remove.intent')
    def remove(self, message):
        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], True)
            if not skill.is_local:
                raise AlreadyRemoved(skill.name)

            if not self.confirm_skill_action(skill, 'remove.confirm'):
                return

            skill.remove()
            skills_data = SkillManager.load_skills_data()
            if skill.name in skills_data:
                del skills_data[skill.name]
            SkillManager.write_skills_data(skills_data)
            self.speak_dialog('remove.complete',
                              dict(skill=self.clean_name(skill)))

    @intent_file_handler('list.skills.intent')
    def handle_list_skills(self, message):
        skills = [skill for skill in self.msm.list() if not skill.is_local]
        shuffle(skills)
        skills = '. '.join(self.clean_name(skill) for skill in skills[:4])
        skills = skills.replace('skill', '').replace('-',' ')
        self.speak_dialog('some.available.skills', dict(skills=skills))

    @intent_file_handler('install.custom.intent')
    def install_custom(self, message):
        link = self.settings.get('installer_link')
        if link:
            repo_name = SkillEntry.extract_repo_name(link)
            with self.handle_msm_errors(repo_name, self.install_word):
                self.msm.install(link)

    @contextmanager
    def handle_msm_errors(self, repo_name, action):
        try:
            yield
        except MsmException as e:
            self.log.error('MSM failed: ' + repr(e))
            if isinstance(e, (SkillNotFound, AlreadyRemoved, AlreadyInstalled)):
                # A valid skill name is sent as the Exception data (passed in to
                # the constructor) for these Exceptions.  The repo_name passed
                # in was a user-spoken name and is likely inexact.
                skill_name = self.clean_repo_name(str(e))
            else:
                skill_name = repo_name

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
            self.speak_dialog(error_dialog,
                              data={'skill': skill_name, 'action': action})
        except StopIteration:
            self.speak_dialog('cancelled')

    def on_web_settings_change(self):
        s = self.settings
        link = s.get('installer_link')
        prev_link = s.get('previous_link')
        auto_install = s.get('auto_install')

        # Check if we should auto-install a skill due to web setting change
        if link and prev_link != link and auto_install:
            s['previous_link'] = link

            self.log.info('Installing from the web...')
            action = self.translate_list('action')[0]
            name = SkillEntry.extract_repo_name(link)
            with self.handle_msm_errors(name, action):
                self.msm.install(link)

    def clean_author(self, skill):
        # TODO: Retrieve and use author from skill-data.json
        if skill.author == "mycroftai":
            return "Mycroft AI"  # totally cheating, I know
        else:
            return skill.author

    def clean_repo_name(self, repo):
        name = repo.replace('skill', '').replace('fallback', '').replace('-',' ').strip()
        return name or repo

    def clean_name(self, skill):
        # TODO: Retrieve and use skill-data.json name instead of repo names
        return self.clean_repo_name(skill.name)

    def confirm_skill_action(self, skill, confirm_dialog):
        resp = self.ask_yesno(confirm_dialog,
                              data={'skill': self.clean_name(skill),
                                    'author': self.clean_author(skill)})
        if resp == 'yes':
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
            names = [self.clean_name(skill) for skill in skills]
            if names:
                response = self.get_response(
                    'choose.skill', num_retries=0,
                    data={'skills': ' '.join([
                        ', '.join(names[:-1]), or_word, names[-1]
                    ])},
                )
                if not response:
                    raise StopIteration
                return self.msm.find_skill(response, skills=skills)
            else:
                raise SkillNotFound(param)


def create_skill():
    return SkillInstallerSkill()
