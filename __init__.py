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
import json
from contextlib import contextmanager
from random import shuffle

from msm import (
    AlreadyInstalled,
    AlreadyRemoved,
    CloneException,
    GitException,
    MsmException,
    MultipleSkillMatches,
    PipRequirementsException,
    SkillEntry,
    SkillNotFound,
    SkillRequirementsException,
    SystemRequirementsException
)

from mycroft import MycroftSkill, intent_handler
from mycroft.api import DeviceApi, is_paired
from mycroft.skills.msm_wrapper import build_msm_config, create_msm


def is_beta(skill_name, skill_list):
    """ Get skill data structure from name. """
    for e in skill_list:
        if e.get('name') == skill_name:
            return e.get('beta', False)
    return False


class SkillInstallerSkill(MycroftSkill):
    _msm = None

    def __init__(self):
        super().__init__()
        self.install_word = self.remove_word = None

    @property
    def msm(self):
        if self._msm is None:
            msm_config = build_msm_config(self.config_core)
            self._msm = create_msm(msm_config)

        return self._msm

    def initialize(self):
        self.settings_change_callback = self.on_web_settings_change
        self.install_word, self.remove_word = self.translate_list('action')

    @intent_handler('install.intent')
    def install(self, message):
        # Failsafe if padatious matches without skill entity.

        if not message.data.get('skill'):
            return self.handle_list_skills(message)

        with self.handle_msm_errors(message.data['skill'], self.install_word):
            skill = self.find_skill(message.data['skill'], False)
            was_beta = is_beta(
                skill.name,
                self.msm.device_skill_state['skills']
            )

            if not was_beta and skill.is_local:
                raise AlreadyInstalled(skill.name)

            if skill.is_local:
                dialog = 'install.reinstall.confirm'
            else:
                dialog = 'install.confirm'

            if not self.confirm_skill_action(skill, dialog):
                return

            if skill.is_local:
                self.msm.remove(skill)
                self.msm.install(skill, origin='voice')
            else:
                self.msm.install(skill, origin='voice')

            self.speak_dialog('install.complete',
                              dict(skill=self.clean_name(skill)))
            self.update_skills_json()

    @intent_handler('install.beta.intent')
    def install_beta(self, message):
        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], False)
            skill.sha = None
            was_beta = is_beta(
                skill.name,
                self.msm.device_skill_state['skills']
            )
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

            if skill.is_local:
                self.msm.update(skill)
            else:
                self.msm.install(skill, origin='voice')

            self.speak_dialog('install.beta.complete',
                              dict(skill=self.clean_name(skill)))
            # Upload manifest to inform backend and Marketplaced of changes
            self.update_skills_json()

    def update_skills_json(self):
        """Update skills manifest if allowed.

        If skill config allows uploading skills manifest and the device is
        properly connected upload the manifest.
        """
        skills_config = self.config_core['skills']
        upload_allowed = skills_config.get('upload_skill_manifest', False)
        if upload_allowed and is_paired():
            try:
                DeviceApi().upload_skills_data(self.msm.device_skill_state)
            except Exception:
                self.log.exception('Could not upload skill manifest')

    @intent_handler('remove.intent')
    def remove(self, message):
        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], True)
            if not skill.is_local:
                raise AlreadyRemoved(skill.name)

            if not self.confirm_skill_action(skill, 'remove.confirm'):
                return

            self.msm.remove(skill)
            self.speak_dialog('remove.complete',
                              dict(skill=self.clean_name(skill)))
            self.update_skills_json()

    @intent_handler('is.installed.intent')
    def is_installed(self, message):
        # Failsafe if padatious matches without skill entity.
        if not message.data.get('skill'):
            return self.handle_list_skills(message)

        with self.handle_msm_errors(message.data['skill'], self.remove_word):
            skill = self.find_skill(message.data['skill'], False)

            if skill.is_local:
                dialog = 'installed'
            else:
                dialog = 'not.installed'

            self.speak_dialog(dialog, dict(skill=self.clean_name(skill)))

    @intent_handler('list.skills.intent')
    def handle_list_skills(self, message):
        skills = [skill for skill in self.msm.all_skills if not skill.is_local]
        shuffle(skills)
        skills = '. '.join(self.clean_name(skill) for skill in skills[:4])
        skills = skills.replace('skill', '').replace('-', ' ')
        self.speak_dialog('some.available.skills', dict(skills=skills))

    @intent_handler('install.custom.intent')
    def install_custom(self, message):
        link = self.settings.get('installer_link')
        if link:
            repo_name = SkillEntry.extract_repo_name(link)
            with self.handle_msm_errors(repo_name, self.install_word):
                self.msm.install(link, origin='')

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
                CloneException: 'error.clone.git',
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
        """Callback on changed settings.

        Handles updating skill installation from Marketplace.
        
        NOTE: Not yet implemented on new Selene backend. 
        These settings have been disabled until the functionality is restored.
        """
        to_install = self.settings.get('to_install', [])
        to_remove = self.settings.get('to_remove', [])
        # If json string convert to proper dict
        if isinstance(to_install, str):
            to_install = json.loads(to_install)
        if isinstance(to_remove, str):
            to_remove = json.loads(to_remove)

        self.handle_marketplace(to_install, to_remove)

    def handle_marketplace(self, to_install, to_remove):
        """Install and remove skills.

        Takes lists of skills to install and remove. Each entry in the list
        is a dict containing

        {
          'name': 'Skill-name',
          'devices': ['uuid1', 'uuid2', ..., "uuidN"]
        }
        The Skill-name skill will be installed if current device matches
        a device in the 'devices' list.

        Arguments:
            to_install (list): Skills entries to install
            to_remove (list): Skill entries to remove
        """
        # Remove skills in to_remove from the to_install list
        # This avoids unnecessary install / uninstall cycles
        self.log.info('to_install: {}'.format(to_install))
        removed = [e['name'] for e in to_remove]
        to_install = [e for e in to_install
                      if e['name'] not in removed]
        self.log.info('to_install: {}'.format(to_install))
        installed, failed = self.__marketplace_install(to_install)
        removed = self.__marketplace_remove(to_remove)
        self.update_skills_json()

        if installed:
            self.log.debug('Successfully installed '
                           '{} skills'.format(len(installed)))
        if failed:
            self.log.debug('Failed to install '
                           '{} skills'.format(len(failed)))
        if removed:
            self.log.debug('Successfully removed '
                           '{} skills'.format(len(removed)))

    def __filter_by_uuid(self, skills):
        """Return only skills intended for this device.

        Keeps entrys where the devices field is None of contains the uuid
        of the current device.

        Arguments:
            skills: skill list from to_install or to_remove

        Returns:
            filtered list
        """
        uuid = DeviceApi().get()['uuid']
        return [s for s in skills
                if not s.get('devices') or uuid in s.get('devices')]

    def __marketplace_install(self, install_list):
        """Install skills as instructed by the marketplace.

        Installs any skills from the install list intended for this device.

        Arguments:
            install_list (list): Skill entries to evaluate for install
        """
        try:
            install_list = self.__filter_by_uuid(install_list)
            # Split skill name from author
            skills = [s['name'].split('.')[0] for s in install_list]

            msm_skills = self.msm.all_skills
            # Remove skills not known to msm
            skills = [s for s in skills if s in [s.name for s in msm_skills]]
            # Remove already installed skills from skills to install
            installed_skills = [s.name for s in msm_skills if s.is_local]
            skills = [s for s in skills if s not in installed_skills]

            self.log.info('Will install {} from the marketplace'.format(skills))

            successes = []
            fails = []
            def install(name):
                """Msm install hook, recording successes and fails."""
                s = self.msm.find_skill(name)
                try:
                    self.msm.install(s, origin='marketplace')
                    successes.append(name)
                except MsmException as e:
                    self.log.error('{} Could not be installed '
                                   'due to {}'.format(name, repr(e)))
                    fails.append(name)

            result = self.msm.apply(install, skills)
            return successes, fails

        except Exception as e:
            self.log.exception('An error occured installing from marketplace '
                           '({}'.format(repr(e)))
            return [], []

    def __marketplace_remove(self, remove_list):
        """Remove skills as instructed by the Marketplace.

        Removes any skills from the remove list intended for this device.

        Arguments:
            remove_list (list): Skill entries to evaluate for removal
        """
        try:
            remove_list = self.__filter_by_uuid(remove_list)

            # Split skill name from author
            skills = [skill['name'].split('.')[0] for skill in remove_list]
            self.log.info('Will remove {} from the marketplace'.format(skills))
            # Remove not installed skills from skills to remove
            installed_skills = [s.name for s in self.msm.all_skills if s.is_local]
            skills = [s for s in skills if s in installed_skills]

            self.log.info('Will remove {} from the marketplace'.format(skills))
            result = self.msm.apply(self.msm.remove, skills)
            return skills
        except Exception as e:
            self.log.error('An error occured installing from marketplace '
                           '({}'.format(repr(e)))
            return []

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
