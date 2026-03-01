import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import gradio as gr
from agent.core import TutorAgent

agent = TutorAgent()

# Get the opening message from the agent
opening = agent.chat("__session_start__")


def respond(message: str, history: list[dict]) -> tuple[str, str | None]:
    """Get agent response. Returns (reply_text, audio_path_or_none)."""
    reply = agent.chat(message)
    return reply, agent.audio_output


with gr.Blocks(title="Mistral Learn") as app:
    gr.Markdown(
        "# ✦ MISTRAL LEARN\n"
        "*Your personal language tutor*"
    )

    chatbot = gr.Chatbot(
        value=[{"role": "assistant", "content": opening}],
        height=500,
    )
    audio_out = gr.Audio(autoplay=True, visible=False, label="🔊 Pronunciation")
    msg = gr.Textbox(
        placeholder="Type a message...",
        show_label=False,
        container=False,
    )

    def user_submit(message: str, history: list[dict]):
        if not message.strip():
            return "", history, gr.update()
        history = history + [{"role": "user", "content": message}]
        reply, audio = respond(message, history)
        history = history + [{"role": "assistant", "content": reply}]
        audio_update = gr.update(value=audio, visible=True) if audio else gr.update(visible=False)
        return "", history, audio_update

    msg.submit(user_submit, [msg, chatbot], [msg, chatbot, audio_out])

if __name__ == "__main__":
    app.launch(theme=gr.themes.Soft())
