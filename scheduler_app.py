
# AI Construction Scheduling Assistant (Chat-Driven)
import streamlit as st
import pdfplumber
import tempfile
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import holidays

st.set_page_config(page_title="AI Construction Scheduler", layout="wide")
st.title("📅 AI Construction Scheduling Assistant")

st.sidebar.title("🗨️ Project Chat Assistant")
st.sidebar.write("Ask the assistant for help building your schedule:")
chat_prompt = st.sidebar.text_area("Chat with Scheduler AI", placeholder="e.g. Build a schedule for a 3000 sqft house in Texas starting June 1st")

# Chat-Driven Schedule Memory (basic simulation)
if 'chat_log' not in st.session_state:
    st.session_state.chat_log = []
if chat_prompt:
    st.session_state.chat_log.append(chat_prompt)
    st.sidebar.success("Message sent to AI!")

if st.session_state.chat_log:
    st.sidebar.subheader("Conversation History")
    for msg in st.session_state.chat_log[::-1]:
        st.sidebar.markdown(f"🗨️ {msg}")

# Section: Upload Specs to Generate Schedule
st.header("📥 Upload Specifications to Generate Schedule")
spec_file = st.file_uploader("Upload Specs or Drawings (PDF)", type="pdf")
extracted_activities = []

if spec_file is not None:
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_file.write(spec_file.read())
        with pdfplumber.open(tmp_file.name) as pdf:
            full_text = "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
            st.text_area("Extracted Text (Preview)", value=full_text[:3000], height=250)

            scope_keywords = {
                "foundation": ["pile", "grade beam", "slab", "rebar"],
                "framing": ["stud", "joist", "sheathing"],
                "hvac": ["heat pump", "FCU", "ERV", "diffuser"],
                "drywall": ["gypsum board", "drywall", "taping", "finishing"],
                "façade": ["siding", "cement board", "WRB"]
            }

            scope_library = {
                "foundation": [
                    "Mobilize Helical Pile Equipment",
                    "Install Helical Piles",
                    "Excavate for pile caps",
                    "Install grade beams",
                    "Pour foundation walls",
                    "Cure and waterproof",
                    "Place rat slab"
                ],
                "framing": [
                    "Install framing walls",
                    "Sheathing",
                    "Interior bearing walls",
                    "Framing inspection"
                ],
                "hvac": [
                    "Install FCU",
                    "Rough-in ductwork",
                    "Install diffusers",
                    "HVAC inspection",
                    "Final connections"
                ],
                "drywall": [
                    "Install drywall",
                    "Tape and finish",
                    "Sand and prep",
                    "Final touch-up"
                ],
                "façade": [
                    "Install WRB",
                    "Cement board siding",
                    "Trims and sealants"
                ]
            }

            for scope, keywords in scope_keywords.items():
                if any(keyword in full_text.lower() for keyword in keywords):
                    extracted_activities += scope_library[scope]
            if extracted_activities:
                st.success("✅ Schedule activities generated from uploaded specs.")
            else:
                st.warning("No matching scopes found in uploaded document.")

# Use either AI-built or manual data
data = extracted_activities if extracted_activities else []
if not data:
    st.header("📋 Manual Task Input")
    data = st.text_area("Enter activities manually (one per line)", placeholder="e.g.\nExcavate\nPour Footings\nInstall Columns").splitlines()

if data and len(data) > 0:
    st.header("🧠 Schedule Settings")
    sqft = st.number_input("Project Size (sqft):", value=3000)
    start_date = st.date_input("Start Date:", value=datetime.today())
    state = st.selectbox("U.S. State (for weather/holidays):", ["FL", "TX", "NY", "CA", "MA", "IL"])
    custom_weather_days = st.slider("Weather delay days/month:", 0, 10, 3)
    custom_buffer_days = st.slider("Buffer days per activity:", 0, 10, 2)

    durations = [max(1, sqft // 1000 + custom_buffer_days)] * len(data)
    current_date = start_date
    holiday_calendar = holidays.country_holidays("US", subdiv=state)

    start_dates, finish_dates = [], []
    for dur in durations:
        count = 0
        while count < dur:
            if current_date.weekday() < 5 and current_date not in holiday_calendar:
                count += 1
            if (count % 30) == 0 and count != 0:
                count += custom_weather_days
            current_date += timedelta(days=1)
        start = current_date - timedelta(days=dur)
        finish = current_date
        start_dates.append(start)
        finish_dates.append(finish)

    df = pd.DataFrame({
        "ID": range(1, len(data)+1),
        "Activity": data,
        "Duration": durations,
        "Start Date": start_dates,
        "Finish Date": finish_dates,
        "Predecessor": ["" if i == 0 else str(i) for i in range(len(data))]
    })

    st.header("📈 Forecast Summary")
    st.markdown(f"- **Start:** {start_dates[0].strftime('%Y-%m-%d')}")
    st.markdown(f"- **End:** {finish_dates[-1].strftime('%Y-%m-%d')}")
    st.markdown(f"- **Total Days:** {(finish_dates[-1] - start_dates[0]).days}")
    st.markdown(f"- **# Activities:** {len(data)}")

    st.header("📊 Gantt Chart Preview")
    fig = px.timeline(df, x_start="Start Date", x_end="Finish Date", y="Activity")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

    if st.download_button("📤 Download Schedule (Excel)", df.to_excel(index=False), file_name="schedule.xlsx"):
        st.success("Download started")
else:
    st.info("Upload specs or manually input activities to get started.")
