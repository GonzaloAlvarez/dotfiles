# Setting Up Obsidian

## What is this
A collection of steps to set up Obsidian.
This is needed because I generally don't synchronize some configuration and plugins, so to avoid conflicts in versions between machines (e.g. win vs mac).

## Get it working

Let's go with the actual steps

### General stuff

**Theme**

Settings -> Appearance -> Themes -> 'Vanilla Amoled'

**Disable Ident Using Tabs**

Settings -> Editor -> __disable__ Ident Using Tabs (I will die on this hill)

**Turn on Community Plugins**

Settings -> Community Plugins -> Turn On

**Change location for new attachments**

Settings -> Files and links -> Default Location for new attachments: extras/attachments

### Plugins

Plugins and their configurations

Install the following plugins:

- Templater
- Dataview
- Git
- Tasks


**Templater**

Create a Templates Folder, such as 'extras/templates'

Create a new note, and use a standard naming, such as '[TEMPLATE] Daily Note.md'. You can see the content of a few of them in the 'obsnotes' repository.

In the Settings -> Templater, change the following:

- Template folder location: extras/templates
- Trigger Templater on new file creation -- Enabled
- Automatic jump to cursor -- Enabled
- Enable Folder Templates -- Enabled  -- folder: /home/daily -- template: extras/templates/[TEMPLATE] Daily Notes.md


**Daily Notes**

In Settings -> Daily Notes, change:

- Date Format to: YYYY-MM/MMDDYY-dddd
- New File Location to: home/daily
- Template File Location: extras/templates/[TEMPLATE] Daily Notes
- Template File Location: extras/templates/[TEMPLATE] Workout


**Tasks**

In Settings -> Tasks, change:

- Global Filter: #task
- Remove Global Filter from Description: Enabled
- Set Created Date on Every Task added: Enabled


**Git**

In Settings -> Git, change:
- Auto commit-and-sync interval: 10
- Auto pull interval: 30
- Specify custom commit message: Updated notes on {{date}} with changed files {{files}}
- Disable notifications: enabled
- Commit author name: Gonzalo Alvarez
- Commit author email: gonzaloab@gmail.com

