import calendar
import datetime
import json
import re
from typing import Optional
from google import genai
from PIL import Image
from pydantic import BaseModel, Field
import streamlit as st
import streamlit.components.v1 as components  # ✅ ต้องมี import นี้
from supabase import create_client

st.set_page_config(page_title="IMC System", layout="wide")

# CSS ปรับแต่งป้ายให้ขนาดเล็ก และดึงระยะห่างระหว่างแถวให้ชิดกัน
st.markdown(
    """
    <style>
    div[data-testid="stPills"] button {
        padding: 2px 8px !important;
        font-size: 12px !important;
        min-height: unset !important;
    }
    div[data-testid="stPills"] {
        margin-bottom: -12px !important;
        margin-top: -8px !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

st.title("🏥 ระบบนำเข้าข้อมูลผู้ป่วย IMC เข้าคลาวด์")

# ดึงค่าความลับผ่าน st.secrets
URL = st.secrets["supabase"]["url"]
KEY = st.secrets["supabase"]["key"]
GEMINI_KEY = st.secrets["google"]["api_key"]

# ================== โค้ดกล้องถ่ายรูป (เวอร์ชันแก้ไข deviceId) ==================
def camera_component():
    """สร้างกล้องและปุ่มควบคุมแบบ iframe แยก"""
    
    camera_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {
                margin: 0;
                padding: 10px;
                font-family: Arial, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
                background: #f5f5f5;
            }
            video {
                width: 100%;
                max-width: 400px;
                max-height: 280px;
                border-radius: 10px;
                border: 2px solid #ccc;
                background: #000;
                object-fit: cover;
            }
            .btn-group {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
                justify-content: center;
                margin-top: 10px;
            }
            .btn-group button {
                padding: 8px 16px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            #btn-capture {
                background: #4CAF50;
            }
            #btn-switch {
                background: #2196F3;
            }
            #btn-cancel {
                background: #f44336;
            }
            .btn-group button:hover {
                opacity: 0.8;
            }
            #status {
                font-size: 12px;
                margin-top: 5px;
                color: #666;
            }
        </style>
    </head>
    <body>
        <video id="video" autoplay playsinline></video>
        <canvas id="canvas" style="display:none;"></canvas>
        <div class="btn-group">
            <button id="btn-capture">📸 ถ่ายรูป</button>
            <button id="btn-switch">🔄 สลับกล้อง</button>
            <button id="btn-cancel">❌ ถ่ายใหม่</button>
        </div>
        <div id="status">กำลังเปิดกล้อง...</div>
        
        <script>
            let currentStream = null;
            let cameras = [];
            let currentCameraIndex = -1;
            let capturedImage = null;

            // ฟังก์ชันค้นหากล้องทั้งหมด
            async function getCameras() {
                try {
                    // ขอ permission ก่อน
                    await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
                        .then(stream => {
                            stream.getTracks().forEach(track => track.stop());
                        });
                    
                    // ค้นหากล้องทั้งหมด
                    const devices = await navigator.mediaDevices.enumerateDevices();
                    cameras = devices.filter(device => device.kind === 'videoinput');
                    
                    console.log('พบกล้อง:', cameras);
                    
                    if (cameras.length === 0) {
                        document.getElementById('status').textContent = '❌ ไม่พบกล้อง';
                        return;
                    }
                    
                    // เลือกกล้องหลังเป็นค่าเริ่มต้น (deviceId ที่มีคำว่า back/environment)
                    currentCameraIndex = cameras.findIndex(camera => 
                        camera.label.toLowerCase().includes('back') ||
                        camera.label.toLowerCase().includes('environment') ||
                        camera.label.toLowerCase().includes('หลัง')
                    );
                    
                    // ถ้าไม่พบกล้องหลัง ให้ใช้กล้องแรก
                    if (currentCameraIndex === -1) {
                        currentCameraIndex = 0;
                    }
                    
                    startCamera(currentCameraIndex);
                    
                } catch (err) {
                    console.error('ไม่สามารถเข้าถึงกล้อง:', err);
                    document.getElementById('status').textContent = '❌ ไม่สามารถเข้าถึงกล้อง';
                    alert('ไม่สามารถเข้าถึงกล้อง: ' + err.message);
                }
            }

            // ฟังก์ชันเปิดกล้องตาม index
            async function startCamera(index) {
                if (currentStream) {
                    currentStream.getTracks().forEach(track => track.stop());
                }
                
                document.getElementById('status').textContent = 'กำลังเปิดกล้อง...';
                
                try {
                    const constraints = {
                        video: {
                            deviceId: { exact: cameras[index].deviceId },
                            width: { ideal: 1280 },
                            height: { ideal: 720 }
                        },
                        audio: false
                    };
                    
                    currentStream = await navigator.mediaDevices.getUserMedia(constraints);
                    
                    const video = document.getElementById('video');
                    video.srcObject = currentStream;
                    await video.play();
                    
                    const cameraLabel = cameras[index].label || 'กล้อง ' + (index + 1);
                    document.getElementById('status').textContent = '📷 ' + cameraLabel;
                    
                } catch (err) {
                    console.error('ไม่สามารถเปิดกล้อง:', err);
                    document.getElementById('status').textContent = '❌ ไม่สามารถเปิดกล้อง';
                    
                    // ถ้าเปิดกล้องที่เลือกไม่ได้ ให้ลองกล้องแรก
                    if (index !== 0) {
                        startCamera(0);
                    } else {
                        alert('ไม่สามารถเปิดกล้องได้: ' + err.message);
                    }
                }
            }

            // ปุ่มสลับกล้อง
            document.getElementById('btn-switch').onclick = function() {
                if (cameras.length <= 1) {
                    alert('พบกล้องเพียงตัวเดียว');
                    return;
                }
                
                // สลับไปกล้องถัดไป
                currentCameraIndex = (currentCameraIndex + 1) % cameras.length;
                startCamera(currentCameraIndex);
            };

            // ปุ่มยกเลิก/ถ่ายใหม่
            document.getElementById('btn-cancel').onclick = function() {
                capturedImage = null;
                document.getElementById('status').textContent = '🔄 พร้อมถ่ายใหม่';
                parent.postMessage({type: 'camera-cancel'}, '*');
            };

            // ปุ่มถ่ายรูป
            document.getElementById('btn-capture').onclick = function() {
                const video = document.getElementById('video');
                const canvas = document.getElementById('canvas');
                
                if (!video.videoWidth || !video.videoHeight) {
                    alert('กล้องยังไม่พร้อม กรุณารอสักครู่');
                    return;
                }
                
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                canvas.getContext('2d').drawImage(video, 0, 0);
                capturedImage = canvas.toDataURL('image/png');
                
                document.getElementById('status').textContent = '✅ ถ่ายรูปแล้ว';
                
                parent.postMessage({
                    type: 'camera-capture', 
                    imageData: capturedImage
                }, '*');
            };

            // เริ่มต้นค้นหาและเปิดกล้อง
            getCameras();
        </script>
    </body>
    </html>
    """
    
    # แสดง iframe
    components.html(camera_html, height=420)
    
    # สร้าง JavaScript listener ใน Streamlit เพื่อรับข้อมูล
    listener_html = """
    <script>
        window.addEventListener('message', function(event) {
            if (event.data.type === 'camera-capture') {
                localStorage.setItem('capturedImage', event.data.imageData);
                window.parent.postMessage({
                    type: 'streamlit:setComponentValue',
                    value: event.data.imageData
                }, '*');
            } else if (event.data.type === 'camera-cancel') {
                localStorage.removeItem('capturedImage');
                window.parent.postMessage({
                    type: 'streamlit:setComponentValue',
                    value: null
                }, '*');
            }
        });
    </script>
    """
    components.html(listener_html, height=0)
    
    return st.session_state.get("camera_image", None)
# ... โค้ดที่เหลือทั้งหมดเหมือนเดิม ...

client = genai.Client(api_key=GEMINI_KEY)
db = create_client(URL, KEY)

if "s_ok" not in st.session_state:
    st.session_state.update(
        s_ok=False,
        h_last="",
        payload={},
        found_patient=None,
        curr_str="",
        imp_count=2,
        auto_search="",
    )

today = datetime.datetime.now().strftime("%d/%m/%Y")


def cal_exp(d_str):
    try:
        dt = datetime.datetime.strptime(d_str, "%d/%m/%Y")
        m_total = dt.month - 1 + 6
        new_year = dt.year + m_total // 12
        new_month = m_total % 12 + 1
        last_day = calendar.monthrange(new_year, new_month)[1]
        return datetime.datetime(
            new_year, new_month, min(dt.day, last_day)
        ).strftime("%d/%m/%Y")
    except:
        return ""


def clean_id_number(raw_id):
    """ทำความสะอาดเลขบัตรให้เป็นตัวเลขล้วน 13 หลัก"""
    if not raw_id:
        return ""
    cleaned = re.sub(r"[^\d]", "", str(raw_id))
    if len(cleaned) == 13:
        return cleaned
    elif len(cleaned) > 13:
        return cleaned[:13]
    return ""


if "regist" not in st.session_state.payload:
    st.session_state.payload["regist"] = today
if "exp" not in st.session_state.payload:
    st.session_state.payload["exp"] = cal_exp(today)

p = st.session_state.payload

c_m1, c_m2 = st.columns(2)
mode = c_m1.radio(
    "📌 ประเภท:",
    (
        "ลงทะเบียนผู้ป่วยใหม่ครั้งแรก (ประวัติเริ่มต้น)",
        "บันทึกการให้บริการ IMC รายครั้ง (ติดตามผล)",
    ),
    horizontal=False,
)
method = c_m2.radio(
    "📸 วิธีนำเข้า:",
    ("ถ่ายรูปจากกล้อง", "อัปโหลดไฟล์รูปภาพ", "📝 กรอกข้อมูลเองด้วยตนเอง"),
    index=2,
    horizontal=False,
)


def get_remaining_time(exp_str):
    try:
        now = datetime.datetime.now()
        exp_dt = datetime.datetime.strptime(exp_str, "%d/%m/%Y")
        delta = exp_dt - now
        if delta.days <= 0:
            return " (สิ้นสุดสิทธิแล้ว)"
        months = delta.days // 30
        rem_days = delta.days % 30
        weeks = rem_days // 7
        res = " (เหลือเวลาประมาณ "
        if months > 0:
            res += f"{months} เดือน "
        if weeks > 0:
            res += f"{weeks} สัปดาห์"
        if months == 0 and weeks == 0:
            res += f"{rem_days} วัน"
        res += ")"
        return res
    except:
        return ""


chk_bi = (
    lambda v: not v.strip()
    or (v.strip().isdigit() and 0 <= int(v.strip()) <= 20)
)


class PatientDataSchema(BaseModel):
    id_num: str = Field(
        description="รหัสประจำตัวประชาชน 13 หลัก (ตัวเลขล้วน ไม่มีขีด)"
    )
    name: str = Field(description="ชื่อ-สกุล รวมคำนำหน้าชื่อ")
    hn: Optional[str] = Field(None, description="หมายเลข HN หากพบ")
    rights: Optional[str] = Field(None, description="สิทธิการรักษา")
    bi0: str = Field(description="ค่า BI วันเข้า IMC (0-20)")
    bix: str = Field(description="ค่า BI ครั้งนี้ (0-20)")
    regist: str = Field(description="วันที่ลงทะเบียน DD/MM/YYYY")
    clinical_note: Optional[str] = Field(
        None, description="หมายเหตุเพิ่มเติมหรือ Clinical Note หากพบในรูป"
    )


# ============================================================
# SYSTEM INSTRUCTION
# ============================================================
SYSTEM_INSTRUCTION = """
คุณคือผู้เชี่ยวชาญระบบ OCR สำหรับการสกัดข้อมูลจากเอกสารทะเบียนราษฎร

**⚠️ สำคัญ: การอ่านเลขประจำตัวประชาชน (id_num)**
1. ในเอกสารทะเบียนราษฎร เลขบัตรจะอยู่ในรูปแบบ: "1-5000-00000-00-9"
2. ให้อ่านตัวเลขทุกตัวที่อยู่ระหว่างขีด (-)
3. นำตัวเลขทั้งหมดมาต่อกันโดยไม่มีขีด: "150000000009"
4. ห้ามใส่ขีดหรือช่องว่างใน id_num เด็ดขาด

**ข้อมูลอื่นๆ ที่ต้องสกัด:**
- name: ชื่อ-นามสกุล พร้อมคำนำหน้า
- hn: หมายเลข HN (ถ้ามี)
- rights: สิทธิการรักษา (ถ้ามี)
- bi0: ค่า BI วันเข้า IMC (0-20)
- bix: ค่า BI ครั้งนี้ (0-20)
- regist: วันที่ในเอกสาร (รูปแบบ DD/MM/YYYY)
- clinical_note: หมายเหตุหรือข้อมูลเพิ่มเติมที่พบในรูป (ถ้ามี)

**ตัวอย่าง:**
- อ่าน "1-5000-00000-00-9" → ส่ง "150000000009"
- อ่าน "นายแมวส้ม สีทอง" → ส่ง "นายแมวส้ม สีทอง"

**ข้อกำหนด:**
1. ตอบกลับเฉพาะ JSON เท่านั้น
2. id_num ต้องเป็นตัวเลขล้วน 13 หลัก
3. ถ้าไม่พบข้อมูล ให้ใส่ค่าว่าง ('')
"""
# ============================================================

from PIL import Image
import streamlit as st

img = None

if method == "ถ่ายรูปจากกล้อง":
    # 1. ปุ่มสลับกล้องหน้า-หลัง
    camera_side = st.radio(
        "เลือกกล้อง:",
        ["กล้องหลัง (Environment)", "กล้องหน้า (User)"],
        horizontal=True,
    )

    facing_mode = (
        "environment" if "กล้องหลัง" in camera_side else "user"
    )

    # 2. เรียกใช้สิทธิ์กล้อง
    st.components.v1.html(
        f"""
        <script>
        navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: {{ ideal: "{facing_mode}" }} }} }});
        </script>
        """,
        height=0,
    )

    # 3. ใช้ st.camera_input แทน camera_component() (จุดที่เคยติด Error)
    img_file = st.camera_input("กดถ่ายรูป", key=f"cam_{facing_mode}")
    if img_file is not None:
        img = Image.open(img_file)

elif method == "อัปโหลดไฟล์รูปภาพ":
    uploaded_file = st.file_uploader(
        "เลือกรูปภาพ", type=["jpg", "jpeg", "png"]
    )
    if uploaded_file is not None:
        img = Image.open(uploaded_file)

# ส่วนแสดง Preview และปุ่มส่งให้ AI แกะข้อมูล
if img is not None:
    st.markdown("---")
    st.image(img, caption="รูปภาพที่เลือก/ถ่าย", use_container_width=True)
    
if img and st.button("🪄 ส่งให้ AI แกะข้อมูล"):
    with st.spinner("AI กำลังแกะ..."):
        pil_img = Image.open(img)
        try:
            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=[
                    pil_img,
                    f"""อ่านข้อมูลจากรูปภาพนี้:

1. หาเลขประจำตัวประชาชน
   - รูปแบบ: 1-5000-00000-00-9
   - อ่านตัวเลขทั้งหมดแล้วต่อกัน: 150000000009
   - ส่งเป็น id_num

2. หาชื่อ-นามสกุล
   - รูปแบบ: นายแมวส้ม สีทอง
   - ส่งเป็น name

3. วันที่ (ถ้ามี)
   - ส่งเป็น regist

4. หมายเหตุหรือข้อมูลเพิ่มเติม (ถ้ามี)
   - ส่งเป็น clinical_note

โหมด: [{mode}]
""",
                ],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": PatientDataSchema,
                    "temperature": 0.0,
                    "system_instruction": SYSTEM_INSTRUCTION,
                },
            )

            if res.parsed:
                if isinstance(res.parsed, BaseModel):
                    data_ai = res.parsed.model_dump()
                else:
                    data_ai = dict(res.parsed)

                # ทำความสะอาด id_num
                if "id_num" in data_ai and data_ai["id_num"]:
                    cleaned = clean_id_number(data_ai["id_num"])
                    if cleaned:
                        data_ai["id_num"] = cleaned
                        st.success(f"✅ พบเลขบัตร: {cleaned}")
                    else:
                        data_ai["id_num"] = ""

                # ถ้ายังไม่มี id_num ให้ค้นหาจากข้อความ
                if not data_ai.get("id_num") and hasattr(res, "text"):
                    match = re.search(
                        r"(\d[\-\s]?\d{4}[\-\s]?\d{5}[\-\s]?\d{2}[\-\s]?\d)",
                        res.text,
                    )
                    if match:
                        cleaned = clean_id_number(match.group(1))
                        if cleaned:
                            data_ai["id_num"] = cleaned
                            st.success(
                                f"✅ พบเลขบัตรจากข้อความ: {cleaned}"
                            )

                    if not data_ai.get("id_num"):
                        match2 = re.search(r"(\d{13})", res.text)
                        if match2:
                            data_ai["id_num"] = match2.group(1)
                            st.success(
                                f"✅ พบเลขบัตร 13 หลักติดกัน: {data_ai['id_num']}"
                            )

                # ตั้งค่า regist
                if "regist" not in data_ai or not data_ai["regist"]:
                    data_ai["regist"] = today
                data_ai["exp"] = cal_exp(data_ai.get("regist", today))

                # แปลง id_num เป็น id เพื่อให้ฟอร์มแสดงผล
                payload_for_form = {
                    "id": data_ai.get("id_num", ""),
                    "name": data_ai.get("name", ""),
                    "hn": data_ai.get("hn", ""),
                    "rights": data_ai.get("rights", ""),
                    "bi0": data_ai.get("bi0", ""),
                    "bix": data_ai.get("bix", ""),
                    "regist": data_ai.get("regist", today),
                    "exp": data_ai.get("exp", ""),
                    "clinical_note": data_ai.get("clinical_note", ""),
                }

                st.session_state.update(
                    payload=payload_for_form, s_ok=False
                )

                # สำหรับหน้า Follow-up
                if not mode.startswith("ลงทะเบียน"):
                    if data_ai.get("id_num"):
                        st.session_state.auto_search = data_ai["id_num"]
                    elif data_ai.get("name"):
                        st.session_state.auto_search = data_ai["name"]

                # แสดงข้อมูลที่อ่านได้
                with st.expander("📋 ข้อมูลที่อ่านได้", expanded=True):
                    st.json(payload_for_form)

                st.rerun()
            else:
                st.error("❌ AI ไม่สามารถอ่านข้อมูลจากรูปภาพนี้ได้")
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาด: {e}")


def trigger_save(
    id_val, mode_str, bi0_val, bia_val, bix_val, table_name, data_payload, c_str
):
    if not id_val.strip() or len(id_val.strip()) > 13:
        st.error("❌ ตรวจสอบรหัส ปชช.")
    elif mode_str.startswith("ลงทะเบียน") and (
        not bi0_val.strip() or not chk_bi(bi0_val)
    ):
        st.error("❌ กรอก BI วันเข้า IMC 0-20")
    elif not mode_str.startswith("ลงทะเบียน") and (
        not bix_val.strip() or not chk_bi(bix_val)
    ):
        st.error("❌ กรอก BI ครั้งนี้ 0-20")
    else:
        if mode_str.startswith("ลงทะเบียน"):
            db.table(table_name).insert(data_payload).execute()
        else:
            db.table("imc_patients").update(data_payload).eq(
                "id", id_val.strip()
            ).execute()
            updated = (
                db.table("imc_patients")
                .select("*")
                .eq("id", id_val.strip())
                .execute()
                .data
            )
            if updated:
                st.session_state.found_patient = updated
        st.balloons()
        st.session_state.update(
            s_ok=True, h_last=c_str, payload={}, curr_str=c_str
        )
        st.rerun()


if method == "📝 กรอกข้อมูลเองด้วยตนเอง" or bool(p):
    if mode.startswith("ลงทะเบียน"):
        st.markdown("---")
        col1, col2 = st.columns(2)

        st.subheader("📝 ฟอร์มลงทะเบียนผู้ป่วยใหม่")
        id_num = col1.text_input(
            "รหัส ปชช. (id):", p.get("id", ""), max_chars=13
        )
        name = col1.text_input("ชื่อ-สกุล:", p.get("name", ""))
        hn = col1.text_input("HN:", p.get("hn", ""))
        hos_dx = col1.selectbox(
            "รพ.วินิจฉัย IMC:",
            ["น่าน", "ปัว", "เวียงสา"],
            index=["น่าน", "ปัว", "เวียงสา"].index(p.get("hos_dx", "น่าน"))
            if p.get("hos_dx") in ["น่าน", "ปัว", "เวียงสา"]
            else 0,
        )

        # --- ส่วนของ hos_pt (ช่องกรอกข้อมูล + ป้ายช่วยเลือก 2 แถว) ---
        if "input_hos_pt" not in st.session_state:
            st.session_state.input_hos_pt = p.get("hos_pt", "")

        hos_pt = col1.text_input(
            "รพ. หลัก:",
            value=st.session_state.input_hos_pt,
            key="input_hos_pt",
        )

        hos_pt_options_row1 = [
            "น่าน",
            "ภูเพียง",
            "ปัว",
            "ท่าวังผา",
            "เชียงกลาง",
            "ทุ่งช้าง",
            "สองแคว",
            "เฉลิมพระเกียรติ",
        ]
        hos_pt_options_row2 = [
            "บ่อเกลือ",
            "เวียงสา",
            "แม่จริม",
            "สันติสุข",
            "นาน้อย",
            "นาหมื่น",
            "บ้านหลวง",
        ]

        def set_hos_pt_r1():
            val = st.session_state.get("pills_hos_r1")
            if val:
                st.session_state.input_hos_pt = val
                st.session_state.pills_hos_r2 = None

        def set_hos_pt_r2():
            val = st.session_state.get("pills_hos_r2")
            if val:
                st.session_state.input_hos_pt = val
                st.session_state.pills_hos_r1 = None

        col1.pills(
            "",
            hos_pt_options_row1,
            key="pills_hos_r1",
            on_change=set_hos_pt_r1,
            label_visibility="collapsed",
        )
        col1.pills(
            "",
            hos_pt_options_row2,
            key="pills_hos_r2",
            on_change=set_hos_pt_r2,
            label_visibility="collapsed",
        )
        # --------------------------------------------------------

        rights = col1.selectbox(
            "สิทธิการรักษา:",
            ["บัตรทอง", "เบิกตรง", "ประกันสังคม", "ชำระเงินเอง"],
            index=["บัตรทอง", "เบิกตรง", "ประกันสังคม", "ชำระเงินเอง"].index(
                p.get("rights", "บัตรทอง")
            )
            if p.get("rights")
            in ["บัตรทอง", "เบิกตรง", "ประกันสังคม", "ชำระเงินเอง"]
            else 0,
        )

        dx = col2.selectbox(
            "กลุ่มโรค:", ["Stroke", "TBI", "SCI", "Hip fracture", "อื่นๆ"]
        )

        enable_imp = col2.toggle(
            "♿ บันทึกข้อมูล Impairment (เพิ่มเติม)", value=False
        )
        imp_choices = [
            "",
            "Swallowing problem",
            "Communication problem",
            "Cognitive and perception problem",
            "Bowel and bladder problem",
            "Mobility problem",
        ]

        imp1, imp2, imp3, imp4, imp5 = "", "", "", "", ""
        if enable_imp:
            col2.write("🩺 **ระบุ Impairment:**")

            c_grid1 = col2.columns(2)
            imp1 = c_grid1[0].selectbox(
                "Impairment (1):", imp_choices, key="imp_1", index=0
            )
            imp2 = c_grid1[1].selectbox(
                "Impairment (2):", imp_choices, key="imp_2", index=0
            )

            if st.session_state.imp_count >= 3:
                c_grid2 = col2.columns(2)
                imp3 = c_grid2[0].selectbox(
                    "Impairment (3):", imp_choices, key="imp_3", index=0
                )
                if st.session_state.imp_count >= 4:
                    imp4 = c_grid2[1].selectbox(
                        "Impairment (4):", imp_choices, key="imp_4", index=0
                    )
            if st.session_state.imp_count >= 5:
                c_grid3 = col2.columns(2)
                imp5 = c_grid3[0].selectbox(
                    "Impairment (5):", imp_choices, key="imp_5", index=0
                )

            if st.session_state.imp_count < 5:
                if col2.button(
                    f"➕ เพิ่มช่องกรอก Impairment ({st.session_state.imp_count + 1})",
                    use_container_width=True,
                ):
                    st.session_state.imp_count += 1
                    st.rerun()

        c_reg, c_reg_btn = col2.columns([2.5, 1])

        if "widget_reg_date" not in st.session_state:
            st.session_state.widget_reg_date = p.get("regist", today)

        def on_regist_date_change():
            st.session_state.my_reg_date = st.session_state.widget_reg_date
            st.session_state.payload["regist"] = (
                st.session_state.widget_reg_date
            )
            st.session_state.payload["exp"] = cal_exp(
                st.session_state.widget_reg_date
            )
            st.session_state.widget_exp_date = cal_exp(
                st.session_state.widget_reg_date
            )

        reg_date_input = c_reg.text_input(
            "วันที่ลงทะเบียน:",
            key="widget_reg_date",
            on_change=on_regist_date_change,
        )

        def set_reg_today():
            st.session_state.widget_reg_date = today
            st.session_state.my_reg_date = today
            st.session_state.payload["regist"] = today
            st.session_state.payload["exp"] = cal_exp(today)
            st.session_state.widget_exp_date = cal_exp(today)

        c_reg_btn.button("📅 วันนี้", key="reg_today", on_click=set_reg_today)

        if "widget_exp_date" not in st.session_state:
            st.session_state.widget_exp_date = p.get(
                "exp", cal_exp(st.session_state.widget_reg_date)
            )

        exp_date = col2.text_input(
            "วันที่ครบกำหนด IMC (+6 เดือนอัตโนมัติ):", key="widget_exp_date"
        )
        bia = col2.text_input("BI แรกรับ [0-20]:", p.get("bia", ""))
        bi0 = col2.text_input("BI วันเข้า IMC [0-20]:", p.get("bi0", ""))

        # 🟢 clinical_note อยู่ระหว่าง bi0 กับ recorder_name
        clinical_note = col2.text_area(
            "📝 Clinical Note (หมายเหตุเพิ่มเติม):",
            value=p.get("clinical_note", ""),
            height=80,
            placeholder="บันทึกข้อมูลเพิ่มเติมเกี่ยวกับผู้ป่วย...",
        )

        recorder_name = col2.text_input(
            "✍️ ชื่อผู้บันทึกข้อมูลเริ่มต้น:", value=p.get("recorder", "")
        )

        payload, table = {
            "id": id_num,
            "name": name,
            "hn": hn,
            "hos_dx": hos_dx,
            "hos_pt": hos_pt,
            "regist": st.session_state.widget_reg_date,
            "exp": exp_date,
            "diagnosis": dx,
            "rights": rights,
            "impairment1": imp1,
            "impairment2": imp2,
            "impairment3": imp3,
            "impairment4": imp4,
            "impairment5": imp5,
            "recorder": recorder_name,
            "bia": bia,
            "bi0": bi0,
            "clinical_note": clinical_note,
        }, "imc_patients"

        curr_str = f"{id_num}{name}{hn}{dx}{rights}{imp1}{imp2}{imp3}{imp4}{imp5}{recorder_name}{exp_date}{bi0}{clinical_note}"
        st.session_state.curr_str = curr_str

        col2.write("")
        if col2.button(
            "💾 บันทึกข้อมูลลง Cloud Database",
            key="btn_reg",
            use_container_width=True,
        ):
            if not recorder_name.strip():
                col2.error("❌ กรุณากรอกชื่อผู้บันทึกข้อมูลก่อนบันทึก")
            else:
                trigger_save(
                    id_num, mode, bi0, bia, "", table, payload, curr_str
                )

if method == "📝 กรอกข้อมูลเองด้วยตนเอง" or bool(p):
    if not mode.startswith("ลงทะเบียน"):
        st.markdown("---")
        col1, col2 = st.columns(2)
        last_visit_index = 0

        st.subheader("📝 บันทึกติดตามผลรายครั้ง (Follow-up)")

        auto_search_value = st.session_state.get("auto_search", "")
        if auto_search_value:
            search_query = col1.text_input(
                "🔎 พิมพ์ชื่อ หรือ รหัส ปชช. เพื่อค้นหา:",
                value=auto_search_value,
            )
            st.session_state.auto_search = ""
        else:
            search_query = col1.text_input(
                "🔎 พิมพ์ชื่อ หรือ รหัส ปชช. เพื่อค้นหา:", value=""
            )

        id_num, history_rows = "", []

        if search_query.strip():
            try:
                q = search_query.strip()
                res_sr = (
                    db.table("imc_patients")
                    .select("*")
                    .or_(f"name.ilike.%{q}%,id.ilike.%{q}%")
                    .execute()
                    .data
                )
                st.session_state.found_patient = res_sr if res_sr else []
                if not res_sr:
                    st.warning(f"❌ ไม่พบผู้ป่วย: {q}")
            except Exception as e:
                st.error(f"❌ ข้อผิดพลาดในการค้นหา: {e}")
                st.session_state.found_patient = []

        found_data = st.session_state.get("found_patient", [])
        last_fu_text, last_bi_text, last_unit_text, last_note_text = (
            "ยังไม่มีข้อมูล",
            "ยังไม่มีข้อมูล",
            "-",
            "-",
        )

        if found_data:
            pt_options = {f"{i['name']} ({i['id']})": i for i in found_data}
            options = list(pt_options.keys())
            default_index = 0
            saved_id = st.session_state.get("selected_patient")
            for i, opt in enumerate(options):
                if pt_options[opt]["id"] == saved_id:
                    default_index = i
                    break
            sel_found = col1.selectbox(
                "🎯 ผลการค้นหา (เลือกรายชื่อ):", options, index=default_index
            )
            p_selected = pt_options[sel_found]
            st.session_state.selected_patient = p_selected["id"]
            id_num = p_selected["id"]

            # [แก้ไขข้อ 4] ใช้ clinical_note ในตารางประวัติแถวแรก
            init_note = p_selected.get("clinical_note") or f"BI แรกรับ: {p_selected.get('bia', '-')}"
            history_rows.append({
                "ครั้งที่": "วันเข้า IMC",
                "วันที่รับบริการ": p_selected.get("regist", "-"),
                "คะแนน BI": p_selected.get("bi0", "-"),
                "หน่วยบริการ": p_selected.get("hos_dx", "-"),
                "Clinical Note": p_selected.get("clinical_note", "-"),
                "ผู้บันทึก": p_selected.get("recorder", "-"),
            })

            # [แก้ไขข้อ 1, 2, 3] ตั้งค่าเริ่มต้นกรณีที่ยังไม่มีการติดตามผล (total imc = 0)
            init_reg_date = p_selected.get("regist", "-")
            last_fu_text = f"{init_reg_date} (ลงทะเบียน IMC)" if init_reg_date != "-" else "-"
            last_unit_text = p_selected.get("hos_dx") or p_selected.get("hos_dx", "-")
            last_bi_text = p_selected.get("bia") or p_selected.get("bi0", "-")
            last_note_text = p_selected.get("clinical_note", "-") or "-"

            for b_idx in range(1, 21):
                if p_selected.get(f"bi{b_idx}") or p_selected.get(f"fu{b_idx}"):
                    last_visit_index = b_idx
                    f_date, f_bi, f_unit, f_note, f_rec = (
                        p_selected.get(f"fu{b_idx}", "-"),
                        p_selected.get(f"bi{b_idx}", "-"),
                        p_selected.get(f"unit{b_idx}", "-"),
                        p_selected.get(f"note{b_idx}", "-"),
                        p_selected.get(f"fu_recorder{b_idx}", "-"),
                    )
                    history_rows.append({
                        "ครั้งที่": f"#{b_idx}",
                        "วันที่รับบริการ": f_date,
                        "คะแนน BI": f_bi,
                        "หน่วยบริการ": f_unit,
                        "Clinical Note": f_note,
                        "ผู้บันทึก": f_rec,
                    })
                    # หากมีข้อมูล follow-up จะ overwrite ค่าแสดงผลล่าสุด
                    last_bi_text = f"{f_bi} (ครั้งที่ {b_idx})"
                    last_fu_text = f"{f_date} (ครั้งที่ {b_idx})"
                    last_unit_text = f_unit
                    last_note_text = f_note

            exp_date_raw = p_selected.get("exp", "-")
            countdown_text = get_remaining_time(exp_date_raw)

            imp_list_saved = []
            for i in range(1, 6):
                imp_val = p_selected.get(f"impairment{i}")
                if imp_val and imp_val.strip():
                    imp_list_saved.append(imp_val)

            detail = f"""
### 📋 รายละเอียดการรักษาก่อนหน้า

- **กลุ่มโรคหลัก:** {p_selected.get('diagnosis','-')} | **สิทธิการรักษา:** {p_selected.get('rights','-')}| **รพ.หลัก:** {p_selected.get('hos_pt','-')}
- **วันที่เข้า IMC:** {p_selected.get('regist','-')} | **{p_selected.get('hos_dx','-')}**
- **วันสิ้นสุดสิทธิ IMC:** {exp_date_raw}{countdown_text}
- **บริการล่าสุดเมื่อ:** {last_fu_text} | ({last_unit_text})
- **BI ล่าสุด:** {last_bi_text}
"""

            if imp_list_saved:
                detail += (
                    f"\n- **Impairment:** {', '.join(imp_list_saved)}"
                )

            detail += f"\n- **Note เดิม:** {last_note_text}"

            col1.markdown(detail)

        if history_rows:
            col1.markdown("---")
            if col1.toggle(
                "👁️ แสดงตารางประวัติการให้บริการย้อนหลัง", value=False
            ):
                col1.dataframe(
                    history_rows, use_container_width=True, hide_index=True
                )
        else:
            if search_query.strip():
                col1.warning("❌ ไม่พบข้อมูลผู้ป่วย")
            id_num = col1.text_input(
                "🪪 หรือระบุรหัส ปชช. 13 หลักโดยตรง:",
                p.get("patient_id", ""),
                max_chars=13,
            )

        next_visit_index = last_visit_index + 1
        times = col2.selectbox(
            "ครั้งที่ให้บริการ (x):",
            [str(i) for i in range(1, 21)],
            index=(next_visit_index - 1)
            if 1 <= next_visit_index <= 20
            else 0,
        )

        if (
            found_data
            and str(times).isdigit()
            and 1 <= int(times) <= last_visit_index
        ):
            col2.warning(
                f"⚠️ ครั้งที่ {times} มีข้อมูลบันทึกไว้แล้ว การบันทึกซ้ำจะเขียนทับข้อมูลเดิม"
            )

        c_fud, c_fud_btn = col2.columns([2.5, 1])
        fu_key = f"fu_val_{times}"
        if fu_key not in st.session_state:
            st.session_state[fu_key] = p.get(f"fu{times}", today)

        def update_fu_date():
            st.session_state.payload[f"fu{times}"] = st.session_state[fu_key]

        fu_date_val = c_fud.text_input(
            f"📅 วันที่รับบริการครั้งที่ {times} (fu{times}):",
            key=fu_key,
            on_change=update_fu_date,
        )

        def set_fu_today():
            st.session_state[fu_key] = today
            st.session_state.payload[f"fu{times}"] = today

        c_fud_btn.button("📅 วันนี้", key="fu_today", on_click=set_fu_today)

        bi_val = col2.text_input(
            f"📊 คะแนน BI ครั้งที่ {times} [0-20] [bi{times}]:",
            value="",
            key=f"inp_bi_{times}",
        )
        unit_val = col2.text_input(
            f"🏢 หน่วยงานที่ให้บริการครั้งที่ {times} (unit{times}):",
            value="",
            key=f"inp_unit_{times}",
        )
        note_val = col2.text_area(
            f"📝 Clinical Note ครั้งที่ {times} (note{times}):",
            value="",
            height=65,
            key=f"inp_note_{times}",
        )
        fu_recorder = col2.text_input(
            f"✍️ ชื่อผู้บันทึกข้อมูลครั้งที่ {times} (fu_recorder{times}):",
            value="",
            key=f"inp_rec_{times}",
        )

        payload = {
            f"fu{times}": st.session_state.payload.get(
                f"fu{times}", fu_date_val
            ),
            f"bi{times}": bi_val,
            f"unit{times}": unit_val,
            f"note{times}": note_val,
            f"fu_recorder{times}": fu_recorder,
            "ให้บริการครั้งที่": times,
            "visit_date": fu_date_val,
            "unit": unit_val,
            "clinical_note": note_val,
            "total": f"รวม ({times} ครั้ง)",
        }
        curr_str = (
            f"{id_num}{fu_date_val}{times}{bi_val}{unit_val}{fu_recorder}"
        )
        st.session_state.curr_str = curr_str

        col2.write("")
        if col2.button(
            "💾 บันทึกข้อมูลลง Cloud Database",
            key="btn_fu",
            use_container_width=True,
        ):
            if not fu_recorder.strip():
                col2.error("❌ กรุณากรอกชื่อผู้บันทึกข้อมูลก่อนกดยืนยัน")
            else:
                trigger_save(
                    id_num,
                    mode,
                    "",
                    "",
                    bi_val,
                    "imc_patients",
                    payload,
                    curr_str,
                )

if st.session_state.s_ok:
    if mode.startswith("ลงทะเบียน"):
        st.success(
            "✅ บันทึกและจัดเก็บข้อมูลลงทะเบียนผู้ป่วยใหม่บนคลาวด์กลางอย่างถาวรสำเร็จ!"
        )
    else:
        st.success(
            "✅ บันทึกและจัดเก็บข้อมูลติดตามผล (Follow-up) บนคลาวด์สำเร็จเรียบร้อยแล้ว!"
        )

if st.session_state.s_ok and st.session_state.h_last != st.session_state.curr_str:
    st.session_state.s_ok = False
