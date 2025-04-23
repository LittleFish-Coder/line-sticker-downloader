# main.py
import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import os
import io
from PIL import Image, ImageSequence
import re

# --- Functions (get_sticker_info, convert_apng_to_gif, download_sticker_button) ---
# (這些函式保持不變，複製你之前的版本即可)
def get_sticker_info(store_url: str) -> list[dict]:
    """
    從 LINE Store 網址獲取貼圖的資訊列表 (包含 URL 和類型)。
    返回格式: [{'url': 'sticker_url', 'type': 'animation' | 'static', 'id': 'sticker_id'}, ...]
    """
    sticker_info_list = []
    try:
        response = requests.get(store_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        # 調整 Class 名稱以符合實際情況 (可能需要更新)
        sticker_elements = soup.find_all('li', class_='FnStickerPreviewItem')
        if not sticker_elements:
             sticker_elements = soup.find_all('li', class_='mdCMN09Li FnStickerPreviewItem') # 備用 class

        if not sticker_elements:
            st.error("找不到貼圖元素。可能是 LINE Store 頁面結構已更改，或者這不是一個有效的貼圖頁面。")
            return []

        seen_ids = set()

        for item in sticker_elements:
            try:
                data_preview = item.get('data-preview')
                if data_preview:
                    sticker_data = json.loads(data_preview)
                    sticker_id = sticker_data.get('id')

                    if sticker_id in seen_ids:
                        continue

                    sticker_type = sticker_data.get('type', 'static').lower()
                    url = None

                    if sticker_type == 'animation':
                        url = sticker_data.get('animationUrl')
                    if not url:
                         url = sticker_data.get('staticUrl')
                         sticker_type = 'static'

                    if url:
                        # 直接儲存包含 id 的完整資訊
                        sticker_info_list.append({'url': url, 'type': sticker_type, 'id': sticker_id})
                        seen_ids.add(sticker_id)

            except json.JSONDecodeError:
                st.warning(f"無法解析其中一個貼圖的 data-preview 屬性: {data_preview}")
            except Exception as e:
                st.warning(f"處理其中一個貼圖時發生錯誤: {e}")

    except requests.exceptions.RequestException as e:
        st.error(f"無法獲取網頁內容：{e}")
        return []
    except Exception as e:
        st.error(f"解析過程中發生未預期的錯誤：{e}")
        return []

    # 去重 (雖然已有 seen_ids，但 double check)
    unique_list = []
    final_seen_ids = set()
    for info in sticker_info_list:
        if info['id'] not in final_seen_ids:
            unique_list.append(info) # 保留完整資訊
            final_seen_ids.add(info['id'])

    return unique_list


def convert_apng_to_gif(image_bytes: bytes) -> bytes | None:
    """將 APNG (從 bytes 輸入) 轉換為 GIF (輸出 bytes)。"""
    try:
        apng = Image.open(io.BytesIO(image_bytes))
        frames = []
        if not getattr(apng, "is_animated", False):
             return None # 不是動畫

        # 提取所有幀
        for frame in ImageSequence.Iterator(apng):
            rgba_frame = Image.new("RGBA", frame.size)
            rgba_frame.paste(frame.convert("RGBA"), (0, 0), frame.convert("RGBA"))
            frames.append(rgba_frame)

        if len(frames) <= 1:
            return None # 只有一幀

        gif_buffer = io.BytesIO()
        frames[0].save(
            gif_buffer,
            format='GIF',
            save_all=True,
            append_images=frames[1:],
            optimize=False,
            duration=apng.info.get('duration', 100),
            loop=apng.info.get('loop', 0),
            transparency=apng.info.get('transparency', None),
            disposal=2
        )
        gif_buffer.seek(0)
        return gif_buffer.getvalue()
    except Exception as e:
        st.error(f"APNG 轉換 GIF 失敗: {e}", icon="⚠️")
        return None

# 使用 cache_data 來緩存下載和轉換的結果，減少重複計算
# 注意：這會為每個貼圖緩存數據，可能會增加記憶體使用量
@st.cache_data(show_spinner=False) # 不顯示內建的 spinner
def get_download_data(sticker_url: str, sticker_type: str, index: int) -> dict | None:
    """
    獲取單個貼圖的下載數據（可能是原始 PNG 或轉換後的 GIF）。
    返回包含 data, file_name, mime 的字典，或在失敗時返回 None。
    """
    try:
        response = requests.get(sticker_url, stream=True)
        response.raise_for_status()
        original_data = response.content

        file_data = original_data
        file_name = f"sticker_{index + 1}.png"
        mime_type = "image/png"
        status = "原始 PNG"

        if sticker_type == 'animation':
            gif_data = convert_apng_to_gif(original_data)
            if gif_data:
                file_data = gif_data
                file_name = f"sticker_{index + 1}.gif"
                mime_type = "image/gif"
                status = "已轉換為 GIF"
            else:
                status = "轉換 GIF 失敗，提供原始 PNG"

        return {"data": file_data, "file_name": file_name, "mime": mime_type, "status": status}

    except requests.exceptions.RequestException as e:
        st.error(f"無法下載貼圖 {index + 1} 的原始資料: {e}", icon="🌐")
        return None
    except Exception as e:
        st.error(f"處理貼圖 {index + 1} 時發生錯誤: {e}", icon="⚙️")
        return None


# --- Streamlit App ---
st.set_page_config(layout="wide")
st.title("🚀 Line Sticker Downloader 🚀")

# --- 初始化 Session State ---
# 檢查 session_state 中是否已儲存貼圖資訊，若無則初始化為 None
if 'sticker_info_list' not in st.session_state:
    st.session_state.sticker_info_list = None
if 'last_loaded_url' not in st.session_state:
    st.session_state.last_loaded_url = ""

# --- 顯示說明 ---
with st.expander("📖 使用說明", expanded=True):
    st.markdown(
        """
        1. 前往 [Line 貼圖商店](https://store.line.me/stickershop/home)。
        2. 找到你喜歡的貼圖，複製其網址。
        3. 將網址貼到下方的輸入框，點擊 **開始抓取貼圖**。
        4. 預覽貼圖並下載靜態或動畫版本（動畫將嘗試轉換為 GIF）。
        """
    )

# --- 輸入和抓取按鈕 ---
default_url = "https://store.line.me/stickershop/product/30397660/"
user_url = st.text_input("輸入 Line 貼圖網址:", key="sticker_url_input", placeholder=default_url)

if st.button("開始抓取貼圖", key="fetch_button"):
    if user_url:
        # 移除方括號內的文字和方括號本身
        cleaned_url = re.sub(r'\[.*?\]', '', user_url)
        # 清理空白並取得最後一個URL（如果有多個的話）
        cleaned_url = cleaned_url.strip().split()[-1]

        # 只有當清理過的 URL 改變時才重新抓取
        if cleaned_url != st.session_state.last_loaded_url:
            with st.spinner("正在努力抓取貼圖中...請稍候..."):
                # 呼叫抓取函式，並將結果存入 session_state
                st.session_state.sticker_info_list = get_sticker_info(cleaned_url)
                st.session_state.last_loaded_url = cleaned_url # 記錄目前載入的 URL
                # 清除舊貼圖的快取數據 (如果 URL 變了)
                get_download_data.clear()
        else:
            st.info("這個 URL 的貼圖已經載入。") # 如果 URL 沒變，提示用戶
    else:
        st.warning("請輸入有效的 Line 貼圖網址。")
        st.session_state.sticker_info_list = None # 清空結果
        st.session_state.last_loaded_url = ""

# --- 顯示貼圖網格 (從 Session State 讀取) ---
# 只有當 session_state 中有資料時才顯示
if st.session_state.sticker_info_list:
    st.success(f"已載入 {len(st.session_state.sticker_info_list)} 張貼圖！(來自 {st.session_state.last_loaded_url})")

    cols_per_row = st.slider("每行顯示幾張貼圖？", min_value=3, max_value=10, value=5, key="cols_slider")

    num_stickers = len(st.session_state.sticker_info_list)
    rows = num_stickers // cols_per_row + (1 if num_stickers % cols_per_row > 0 else 0)

    for i in range(rows):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            sticker_index = i * cols_per_row + j
            if sticker_index < num_stickers:
                with cols[j]:
                    # 從 session_state 獲取當前貼圖的資訊
                    current_info = st.session_state.sticker_info_list[sticker_index]
                    st.image(current_info['url'], width=100) # 顯示預覽

                    # 準備下載數據 (使用快取函式)
                    download_info = get_download_data(current_info['url'], current_info['type'], sticker_index)

                    if download_info:
                        st.download_button(
                            label=f"下載 {os.path.basename(download_info['file_name'])}",
                            data=download_info['data'],
                            file_name=download_info['file_name'],
                            mime=download_info['mime'],
                            key=f"download_{current_info['id']}" # 使用貼圖 ID 作為 key
                        )
                        # 可以選擇性地顯示轉換狀態
                        st.caption(download_info['status'])
                    else:
                        # 如果 get_download_data 失敗，顯示錯誤訊息
                        st.error(f"無法準備貼圖 {sticker_index + 1} 的下載")


elif st.session_state.last_loaded_url and st.session_state.sticker_info_list is not None:
     # 處理抓取後沒有結果的情況 (例如 URL 無效或找不到貼圖)
     st.warning(f"無法從 {st.session_state.last_loaded_url} 找到任何貼圖。請檢查網址。")


st.markdown("---")
st.markdown("Created with Streamlit by 程式夥伴")