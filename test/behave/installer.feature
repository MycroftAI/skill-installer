Feature: mycroft-installer

  Scenario: list available
    Given an english speaking user
     When the user says "list available skills"
     Then "mycroft-installer" should reply with dialog from "some.available.skills.dialog"

  Scenario: check if skill is installed
    Given an english speaking user
     When the user says "is mycroft installer installed"
     Then "mycroft-installer" should reply with dialog from "installed.dialog"

