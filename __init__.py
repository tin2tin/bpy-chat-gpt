# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name": "Screenwriter Assistant Chat GPT",
    "author": "Joshua Knauber, tintwotin",
    "description": "Integrates the Chat GPT API into Blender for script generation",
    "blender": (3, 0, 0),
    "version": (0, 0, 1),
    "location": "Text Editor > Screenwriter Tab > Screenwriter Assistant",
    "warning": "",
    "category": "Text Editor",
}

import urllib.request
import json, re
import bpy, aud
import textwrap
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    IntProperty,
)
from bpy.types import (
    Operator,
    AddonPreferences,
    Panel,
)

ENDPOINT = "https://api.openai.com/v1/chat/completions"


class ChatGPTAddonPreferences(AddonPreferences):
    bl_idname = __name__

    api_key: bpy.props.StringProperty(
        name="API Key",
        description="API Key for the Chat GPT API",
        subtype="PASSWORD",
        default="",
    )

    soundselect: EnumProperty(
        name="Sound",
        items={
            ("ding", "Ding", "A simple bell sound"),
            ("coin", "Coin", "A Mario-like coin sound"),
            ("user", "User", "Load a custom sound file"),
        },
        default="ding",
    )

    usersound: StringProperty(
        name="User",
        description="Load a custom sound from your computer",
        subtype="FILE_PATH",
        default="",
        maxlen=1024,
    )

    playsound: BoolProperty(
        name="Audio Notification",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "api_key")
        3
        box = layout.box()
        box.prop(self, "playsound")
        row = box.row()
        row.prop(self, "soundselect")
        if self.soundselect == "user":
            row.prop(self, "usersound", text="")
        row.operator("renderreminder.play_notification", text="", icon="PLAY")
        row.active = self.playsound


class GPT_OT_sound_notification(Operator):
    """Test your notification settings"""

    bl_idname = "renderreminder.play_notification"
    bl_label = "Test Notification"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        preferences = context.preferences
        addon_prefs = preferences.addons[__name__].preferences
        if addon_prefs.playsound:
            device = aud.Device()

            def coinSound():
                sound = aud.Sound("")
                handle = device.play(
                    sound.triangle(1000)
                    .highpass(20)
                    .lowpass(2000)
                    .ADSR(0, 0.5, 1, 0)
                    .fadeout(0.1, 0.1)
                    .limit(0, 1)
                )

                handle = device.play(
                    sound.triangle(1500)
                    .highpass(20)
                    .lowpass(2000)
                    .ADSR(0, 0.5, 1, 0)
                    .fadeout(0.2, 0.2)
                    .delay(0.1)
                    .limit(0, 1)
                )

            def ding():
                sound = aud.Sound("")
                handle = device.play(
                    sound.triangle(3000)
                    .highpass(20)
                    .lowpass(1000)
                    .ADSR(0, 0.5, 1, 0)
                    .fadeout(0, 1)
                    .limit(0, 1)
                )

            if addon_prefs.soundselect == "ding":
                ding()
            if addon_prefs.soundselect == "coin":
                coinSound()
            if addon_prefs.soundselect == "user":
                file = str(addon_prefs.usersound)
                sound = aud.Sound(file)
                handle = device.play(sound)
        return {"FINISHED"}


def label_multiline(context, text, parent):
    chars = int(context.region.width / 7)
    wrapper = textwrap.TextWrapper(width=chars)
    text_lines = [
        wrapped_line
        for line in text.splitlines()
        for wrapped_line in wrapper.wrap(text=line)
    ]
    [parent.label(text=text_line) for text_line in text_lines]


class ChatHistoryItem(bpy.types.PropertyGroup):
    input: bpy.props.StringProperty()

    output: bpy.props.StringProperty()


class ChatGPTAddonProperties(bpy.types.PropertyGroup):
    chat_history: bpy.props.CollectionProperty(type=ChatHistoryItem)

    chat_gpt_select_prefix: bpy.props.StringProperty(
        name="Select Prefix",
        description="Selection prefix ext",
        default="",
        options={"TEXTEDIT_UPDATE"},
    )

    chat_gpt_prefix: bpy.props.StringProperty(
        name="Prefix",
        description="Prefix text",
        default="",
        options={"TEXTEDIT_UPDATE"},
    )

    chat_gpt_input: bpy.props.StringProperty(
        name="Input",
        description="Input text for the Chat GPT API",
        default="",
        options={"TEXTEDIT_UPDATE"},
    )


class GPT_OT_SendSelection(Operator):
    bl_label = "Send Selection"
    bl_idname = "gpt.send_selection"

    @classmethod
    def poll(cls, context):
        gpt = context.scene.gpt
        return gpt.chat_gpt_select_prefix != ""

    def execute(self, context):
        gpt = context.scene.gpt

        try:
            # Get the active text editor
            text_editor = bpy.context.space_data.text

            # Get the text content
            text_content = text_editor.as_string()

            output = process_message(
                request_selection_answer(
                    gpt.chat_gpt_select_prefix + ": " + text_content
                )
            )

            text = bpy.context.space_data.text
            if text is None:
                text = bpy.data.texts.new("Chat GPT")
                bpy.context.space_data.text = text
            text.write(output)

            item = gpt.chat_history.add()
            item.input = gpt.chat_gpt_select_prefix
            item.output = output
            # gpt.chat_gpt_input = ''
            bpy.ops.renderreminder.play_notification()
        except Exception as e:
            self.report({"ERROR"}, str(e))
        return {"FINISHED"}


class GPT_OT_SendMessage(Operator):
    bl_label = "Send Message"
    bl_idname = "gpt.send_message"

    @classmethod
    def poll(cls, context):
        return (
            context.scene.gpt.chat_gpt_input != ""
            or context.scene.gpt.chat_gpt_prefix != ""
        )

    def execute(self, context):
        gpt = context.scene.gpt

        try:
            output = process_message(
                request_answer(gpt.chat_gpt_prefix + " " + gpt.chat_gpt_input)
            )

            text = bpy.context.space_data.text
            if text is None:
                text = bpy.data.texts.new("Chat GPT")
                bpy.context.space_data.text = text
            text.write(output)

            item = gpt.chat_history.add()
            item.input = gpt.chat_gpt_input
            item.output = output
            # gpt.chat_gpt_input = ''
            bpy.ops.renderreminder.play_notification()
        except Exception as e:
            self.report({"ERROR"}, str(e))
        return {"FINISHED"}


class GPT_PT_MainPanel(Panel):
    bl_label = "Screenwriter Assistant"
    bl_idname = "GPT_PT_MainPanel"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "Screenwriter"

    def draw(self, context):
        layout = self.layout
        gpt = context.scene.gpt

        layout = self.layout
        layout.label(text="Write")
        layout = layout.box()
        wide = layout
        wide.scale_y = 1.25
        wide.prop(gpt, "chat_gpt_prefix", text="")  # GPT_OT_SendSelection

        row = layout.row(align=True)

        row.prop(gpt, "chat_gpt_input", text="")
        row.operator("gpt.send_message", text="", icon="PLAY")

        box = layout.column(align=True)
        box.scale_y = 1
        text = gpt.chat_gpt_prefix + "\n" + gpt.chat_gpt_input
        label_multiline(context=context, text=text, parent=box)

        layout = self.layout
        layout.column(align=True)
        layout.label(text="Rewrite")
        row = layout.row(align=True)
        row.scale_y = 1.25
        row.prop(gpt, "chat_gpt_select_prefix", text="")
        row.operator("gpt.send_selection", text="", icon="PLAY")


def process_message(message: str) -> str:
    """Process the message to make it more readable"""
    message = re.sub(r"[\"#/@<>{}`+=|]", "", message)
    lines = message.split("\n")

    processed = []
    in_code_block = False
    for line in lines:
        line = line.rstrip()
        if line == "```python":
            in_code_block = True
        elif in_code_block:
            if line == "```":
                in_code_block = False
            else:
                processed.append(line)
        elif line:
            words = line.split(" ")
            while len(words) > 0:
                line = ""
                while len(words) > 0:
                    line += words.pop(0) + " "
                processed.append(line.rstrip())
        else:
            processed.append("")
    return "\n".join(processed)


def request_selection_answer(text: str) -> str:
    """Request an answer from the Chat GPT API"""
    data = {
        "model": "gpt-4",
        "messages": [
            {
                "role": "system",
                "content": "You are an assistant doing what your are asked, without commenting.",
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bpy.context.preferences.addons[__name__].preferences.api_key}",
    }

    req = urllib.request.Request(ENDPOINT, json.dumps(data).encode(), headers)

    with urllib.request.urlopen(req) as response:
        answer = json.loads(response.read().decode())
    if "error" in answer:
        raise Exception(answer["error"]["message"])
    output = answer["choices"][0]["message"]["content"]
    return output


def request_answer(text: str) -> str:
    """Request an answer from the Chat GPT API"""
    data = {
        "model": "gpt-4",
        "messages": [
            {
                "role": "system",
                "content": "You are a screenwriter helping out writing a screenplay using fountain screenplay formatting. Write emotions as actions. Use subtext. Do not let any character say what they are feeling.",
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bpy.context.preferences.addons[__name__].preferences.api_key}",
    }

    req = urllib.request.Request(ENDPOINT, json.dumps(data).encode(), headers)

    with urllib.request.urlopen(req) as response:
        answer = json.loads(response.read().decode())
    if "error" in answer:
        raise Exception(answer["error"]["message"])
    output = answer["choices"][0]["message"]["content"]
    return output


classes = (
    GPT_OT_sound_notification,
    GPT_OT_SendSelection,
    GPT_PT_MainPanel,
    GPT_OT_SendMessage,
    ChatHistoryItem,
    ChatGPTAddonProperties,
    ChatGPTAddonPreferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gpt = bpy.props.PointerProperty(type=ChatGPTAddonProperties)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.gpt


if __name__ == "__main__":
    register()
