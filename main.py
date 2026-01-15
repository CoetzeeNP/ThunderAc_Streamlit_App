import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
from google import genai
from google.genai import types
from openai import OpenAI as OpenAIClient
import html
import re

SHEET_NAME = "Gemini Logs"
MODEL_MAPPING = {
    "gemini-3-pro-preview": "gemini-3-pro-preview",
    "ChatGPT 5.2": "gpt-5.2-thinking"
}

AUTHORIZED_STUDENT_IDS = ["Thunder"]

header_container = st.container()
with header_container:
    st.image("combined_logo.jpg", width="stretch")

st.title("Business Planning Assistant")

st.set_page_config(layout="wide")

# --- Updated Firebase Connection ---
@st.cache_resource
def get_firebase_connection():
    try:
        if not firebase_admin._apps:
            cred_info = dict(st.secrets["firebase_service_account"])
            cred_info["private_key"] = cred_info["private_key"].replace("\\n", "\n")

            # Ensure the URL is clean
            db_url = st.secrets["firebase_db_url"].strip()

            cred = credentials.Certificate(cred_info)
            firebase_admin.initialize_app(cred, {
                'databaseURL': db_url
            })

        # Return the root reference
        return db.reference("/")
    except Exception as e:
        st.error(f"Firebase Init Error: {e}")
        return None


db_ref = get_firebase_connection()


# --- Updated Logging Function with Debugging ---
def save_to_firebase(user_id, model_name, prompt_, full_response, interaction_type):
    if db_ref:
        try:
            # We sanitize the user_id (Firebase keys can't contain '.', '#', '$', '[', or ']')
            clean_user_id = str(user_id).replace(".", "_")

            # Use a timestamp-based key to keep entries in order
            timestamp_key = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Store data at: /logs/user_id/timestamp_key
            db_ref.child("logs").child(clean_user_id).child(timestamp_key).set({
                "model_name": model_name,
                "prompt": prompt_,
                "response": full_response,
                "interaction_type": interaction_type,
                "full_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            return True
        except Exception as e:
            st.error(f"Firebase Logging error: {e}")
            return False


def get_ai_response(model_selection, chat_history, system_instruction_text):
    try:
        # --- PRIMARY: Google Gemini ---
        client = genai.Client(api_key=st.secrets["api_keys"]["google"])
        api_contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part.from_text(text=m["content"])]
            ) for m in chat_history
        ]

        response = client.models.generate_content(
            model=MODEL_MAPPING[model_selection],
            contents=api_contents,
            config=types.GenerateContentConfig(
                temperature=0.7,
                system_instruction=system_instruction_text
            )
        )
        return response.text

    except Exception as e:
        # Check if it's a 502 error
        error_msg = str(e)
        if "502" in error_msg or "Bad Gateway" in error_msg:
            st.warning("Gemini is currently unavailable (502). Switching to ChatGPT 5.2 fallback...")

            try:
                # --- FALLBACK: ChatGPT 5.2 ---
                # Note: Assuming 'gpt-5.2' is the model ID in the 2026 OpenAI API
                oa_client = OpenAIClient(api_key=st.secrets["api_keys"]["openai"])

                # Format history for OpenAI
                oa_messages = [{"role": "system", "content": system_instruction_text}]
                for m in chat_history:
                    role = "assistant" if m["role"] == "model" else m["role"]
                    oa_messages.append({"role": role, "content": m["content"]})

                # Using the 2026 responses.create or chat.completions.create
                fallback_response = oa_client.chat.completions.create(
                    model="gpt-5.2",
                    messages=oa_messages,
                    temperature=0.7
                )
                return fallback_response.choices[0].message.content

            except Exception as fallback_err:
                return f"Both models failed. Gemini Error: {error_msg} | OpenAI Error: {str(fallback_err)}"

        return f"Error: {error_msg}"


if "messages" not in st.session_state: st.session_state["messages"] = []
if "feedback_pending" not in st.session_state: st.session_state["feedback_pending"] = False
if "authenticated" not in st.session_state: st.session_state["authenticated"] = False
if "current_user" not in st.session_state: st.session_state["current_user"] = None


def handle_feedback(understood: bool):
    interaction = "UNDERSTOOD_FEEDBACK" if understood else "CLARIFICATION_REQUESTED"
    last_user_prompt = st.session_state["messages"][-2]["content"] # The prompt before the AI reply
    last_ai_reply = st.session_state["messages"][-1]["content"]

    save_to_firebase(st.session_state["current_user"], selected_label, last_ai_reply, interaction, "FEEDBACK_EVENT")

    if not understood:
        clarification_prompt = f"I don't understand the previous explanation: '{last_ai_reply}'. Please break it down further."
        st.session_state["messages"].append({"role": "user", "content": clarification_prompt})

        ai_reply = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)

        save_to_firebase(st.session_state["current_user"], selected_label, clarification_prompt, ai_reply, "CLARIFICATION_RESPONSE")

        st.session_state["messages"].append({"role": "assistant", "content": ai_reply})
        st.session_state["feedback_pending"] = True
    else:
        st.session_state["feedback_pending"] = False

with st.sidebar:
    st.image("icdf.png", width="stretch")
    st.header("Business Planning Assistant Menu")
    st.write(f"**Logged in as:** {st.session_state['current_user']}")
    if not st.session_state["authenticated"]:
        u_id = st.text_input("Enter Student ID", type="password")
        # Placing login button in a column to keep it consistent
        if st.button("Login", use_container_width=True):
            if u_id in AUTHORIZED_STUDENT_IDS:
                st.session_state["authenticated"] = True
                st.session_state["current_user"] = u_id
                st.success("Welcome!")
                st.rerun()
            else:
                st.error("Invalid Student ID")
    else:
        # Create two columns for the buttons
        col1, col2 = st.columns(2)

        with col1:
            if st.button("Logout", use_container_width=True):
                st.session_state.clear()
                st.rerun()

        with col2:
            # Your new MS Form button
            st.link_button("Feedback", "https://forms.office.com/Pages/ResponsePage.aspx?id=uRv8jg-5SEq_bLoGhhk7gBvkZQsfRhhErcivaQmEhItUNENSMEJNQTM3UzQ1RlBMSFBUVTFKTFg2VS4u", use_container_width=True)


    if st.session_state["authenticated"]:
        st.markdown("---")
        st.write("**Clear the Chat Screen**")
        # --- NEW CLEAR CHAT BUTTON ---
        if st.button("Clear Chat", use_container_width=True, type="secondary"):
            st.session_state["messages"] = []
            st.session_state["feedback_pending"] = False
            st.rerun()
        # -----------------------------

        with st.sidebar:
            st.markdown("---")
            # Only shows if you check this box
            dev_mode = st.checkbox("Developer Settings", value=False)

            if dev_mode:
                selected_label = st.selectbox("AI Model", list(MODEL_MAPPING.keys()))
                system_instruction_input = st.text_area("System Message",
                                                        "Business Planning Assistant")
            else:
                # Default values when hidden
                selected_label = "gemini-3-pro-preview"
                system_instruction_input = "Business Planning Assistant"





# Check if user is logged in
if not st.session_state["authenticated"]:
    st.warning("Please login with an authorized Student ID in the sidebar.")
    with st.container():
        st.markdown("### You need to be signed in to get access to the Business Planning Assistant")
        st.info("Additional dashboard features will appear here once you are verified.")
else:
    st.info("You are welcome to start chatting with the Assistant using the text box below!")

    # 1. DISPLAY CHAT HISTORY
    # This loop renders previous messages in bounded boxes
    for msg in st.session_state["messages"]:
        is_user = msg["role"] == "user"
        label = st.session_state["current_user"] if is_user else "Business Planning Assistant"

        # Remove the avatar parameter completely to use defaults/cleaner look
        with st.chat_message(msg["role"]):
            with st.container(border=True):
                st.markdown(f"**{label}:**")
                st.markdown(msg["content"])

    # 2. CHAT INPUT
    input_placeholder = "Please give feedback on the last answer..." if st.session_state[
        "feedback_pending"] else "Ask your question here..."
    prompt = st.chat_input(input_placeholder, disabled=st.session_state["feedback_pending"])

    if prompt:
        # Save and Display Student Message
        st.session_state["messages"].append({"role": "user", "content": prompt})

        # Remove avatar parameter here as well
        with st.chat_message("user"):
            with st.container(border=True):
                st.markdown("**Student:**")
                st.markdown(prompt)

        # Remove avatar parameter here as well
        with st.chat_message("assistant"):
            with st.container(border=True):
                st.markdown("**Business Planning Assistant:**")
                with st.spinner("Thinking..."):
                    reply = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)
                    st.markdown(reply)

        # Log interaction to Firebase
        save_to_firebase(
            st.session_state["current_user"],
            selected_label,
            prompt,
            reply,
            "INITIAL_QUERY"
        )

        # Update Session State
        st.session_state["messages"].append({"role": "assistant", "content": reply})
        st.session_state["feedback_pending"] = True
        st.rerun()

    # 3. FEEDBACK SECTION
    if st.session_state["feedback_pending"]:
        st.divider()
        st.info("Did you understand the assistants response?")

        # Keep your custom styling for the feedback buttons
        st.markdown("""
            <style>
            div[data-testid="stColumn"]:nth-of-type(1) button { background-color: #28a745 !important; color: white !important; }
            div[data-testid="stColumn"]:nth-of-type(2) button { background-color: #dc3545 !important; color: white !important; }
            </style>
            """, unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.button("I understand!", on_click=handle_feedback, args=(True,), use_container_width=True)
        with c2:
            st.button("I need some help!", on_click=handle_feedback, args=(False,), use_container_width=True)
