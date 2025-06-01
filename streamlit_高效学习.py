# web.py (修改后 - v8: 解决 SyntaxError: 'return' outside function)
import streamlit as st
import time
import datetime
import threading
import os
import math
# 注意：pygame.mixer 的初始化和使用主要在线程中进行，但 Streamlit 主线程需要知道音频路径是否存在
# 所以我们主要在主线程（UI）中进行路径检查和转换，然后将转换后的绝对路径传递给线程
import pygame # 保留导入，虽然主要在线程使用，但为了代码完整性和潜在的初始化检查

from 学习函数 import run_audio_timer  # 导入后端函数

# --- 获取当前脚本所在的目录 ---
# 这段代码必须在文件的顶部，确保 __file__ 指向当前的 web.py 文件
# os.path.abspath(__file__) 获取当前文件的绝对路径
# os.path.dirname() 获取这个文件所在的目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# print(f"脚本所在目录: {SCRIPT_DIR}") # 可以 uncomment 这行用于调试，看看脚本目录是否正确


# --- 辅助函数：将路径转换为基于脚本目录的绝对路径 ---
def get_absolute_path_relative_to_script(path):
    """
    将一个路径转换为基于当前脚本所在目录的绝对路径。
    如果输入的 path 本身就是绝对路径，则直接返回。
    如果输入的 path 是 None 或空字符串，返回 None。
    """
    # 使用 strip() 移除首尾空白，防止用户不小心输入空格
    cleaned_path = path.strip() if isinstance(path, str) else None
    if not cleaned_path: # 处理 None、空字符串或只有空白的情况
        return None
    if os.path.isabs(cleaned_path): # 如果输入已经是绝对路径，直接返回
        return cleaned_path
    # 如果是相对路径，与脚本目录拼接，生成绝对路径
    # os.path.normpath 会清理路径中的冗余分隔符等
    return os.path.normpath(os.path.join(SCRIPT_DIR, cleaned_path))

# --- Streamlit 应用标题和说明 (主区域) ---
st.title("高效学习法")
st.write("这个应用会在3-5分钟随机提示，闭眼深呼吸10秒，持续学习90分钟结束。")
st.write("然后休息20分钟，冥想、短睡等。释放大脑内存，为接下来的学习做准备。详情可点开侧边栏的视频链接观看") # 小修改，大脑内存更流畅

# --- 使用 Session State 管理应用状态 ---
# 初始化 session state 变量
if 'is_running' not in st.session_state:
    st.session_state.is_running = False
if 'is_paused' not in st.session_state:
    st.session_state.is_paused = False
if 'log_messages' not in st.session_state:
    st.session_state.log_messages = [] # 存储日志
if 'time_records' not in st.session_state:
    st.session_state.time_records = [] # 存储提示音时间
if 'timer_thread' not in st.session_state:
    st.session_state.timer_thread = None # 线程对象
if 'stop_event' not in st.session_state:
     st.session_state.stop_event = threading.Event() # 停止事件对象
if 'pause_event' not in st.session_state:
     st.session_state.pause_event = threading.Event() # 暂停事件对象
if 'last_status' not in st.session_state: # 存储上次任务结束时的最终状态文字，用于下次启动前的显示
    st.session_state.last_status = None

# status_data: 实时状态字典，由线程更新，UI读取显示
# 确保 status_data 及其所有键始终存在，即使是 None 或 0
if 'status_data' not in st.session_state or not isinstance(st.session_state.status_data, dict):
    st.session_state.status_data = {
        'elapsed_time': 0.0, # 实际运行时间 (秒)
        'remaining_time': 0.0, # 常规计时阶段剩余时间 (秒)
        'play_count': 0, # 常规提示音播放次数
        'current_status': '空闲', # 初始状态描述
        # 线程内部状态：'idle', 'starting', 'running', 'paused', 'stopping', 'finishing_regular', 'finishing', 'finished'
        'thread_status': 'idle',
        'start_time': None, # 任务开始的系统时间戳
        'paused_duration': 0.0, # 累计暂停时长 (秒)
        'pause_start_time': None, # 当前暂停开始的系统时间戳 (线程内部使用)
        'current_pause_duration_display': 0.0 # 当前这次暂停已持续的时长 (秒，线程实时更新)
    }
# 确保默认的路径配置也保存在 session state 中，方便下次加载
# 默认值可以是相对路径
if 'regular_sound_path' not in st.session_state:
    st.session_state.regular_sound_path = '剑鸣2秒.wav'
if 'final_sound_path' not in st.session_state:
    st.session_state.final_sound_path = 'Eyecatch.wav'
if 'min_interval_minutes' not in st.session_state:
     st.session_state.min_interval_minutes = 3
if 'max_interval_minutes' not in st.session_state:
     st.session_state.max_interval_minutes = 5
if 'total_duration_minutes' not in st.session_state:
     st.session_state.total_duration_minutes = 90
if 'final_duration_seconds' not in st.session_state:
     st.session_state.final_duration_seconds = 10
if 'volume_control' not in st.session_state:
     st.session_state.volume_control = 0.1


# --- 时间格式化辅助函数 ---
def format_seconds_to_minutes_seconds(seconds):
    """将秒数转换为 'MM分钟 SS秒' 的格式"""
    if seconds is None or seconds < 0:
        seconds = 0
    minutes = math.floor(seconds / 60)
    remaining_seconds = math.floor(seconds % 60)
    # 确保显示整数
    return f"{int(minutes)}分钟 {int(remaining_seconds)}秒"

# --- 配置区域 (侧边栏) ---
with st.sidebar:
    st.header("配置")

    # 使用 session_state 中保存的值作为默认值
    # 当用户清空输入框时，st.text_input 的 value 会变成空字符串 ""
    regular_sound_path_input = st.text_input("常规提示音文件路径 (.wav 推荐):", value=st.session_state.regular_sound_path, key='sidebar_regular_path_input')
    final_sound_path_input = st.text_input("结束提示音文件路径 (.wav 推荐):", value=st.session_state.final_sound_path, key='sidebar_final_path_input')

    # --- 检查文件是否存在，使用转换后的绝对路径进行检查 ---
    # 将用户输入的路径转换为基于脚本目录的绝对路径，以便检查
    resolved_regular_path_input = get_absolute_path_relative_to_script(regular_sound_path_input)
    resolved_final_path_input = get_absolute_path_relative_to_script(final_sound_path_input)

    # 检查转换后的路径是否存在，如果不存在给予警告
    # 注意：这里只检查转换后的路径，因为这是程序实际使用的路径
    # 同时检查 resolved_path 是否是 None 或空字符串
    regular_file_valid_and_exists = (resolved_regular_path_input is not None) and os.path.exists(resolved_regular_path_input)
    final_file_valid_and_exists = (resolved_final_path_input is not None) and os.path.exists(resolved_final_path_input)
    # 文件都有效且存在才认为配置有效
    files_exist_config = regular_file_valid_and_exists and final_file_valid_and_exists

    # 显示警告时，同时显示用户输入的路径和实际检查的绝对路径，更清晰
    # 检查用户输入是否非空，如果为空则不显示警告，只在启动时检查
    if regular_sound_path_input.strip() and not regular_file_valid_and_exists:
        st.warning(f"警告：常规提示音文件 '{regular_sound_path_input}' (实际检查: '{resolved_regular_path_input if resolved_regular_path_input else '路径无效或为空'}') 不存在!")
    if final_sound_path_input.strip() and not final_file_valid_and_exists:
        st.warning(f"警告：结束提示音文件 '{final_sound_path_input}' (实际检查: '{resolved_final_path_input if resolved_final_path_input else '路径无效或为空'}') 不存在!")


    # 时间间隔和时长输入 (从 session state 加载值)
    min_interval_minutes_input = st.number_input("最小常规提示音间隔 (分钟):", min_value=1, value=st.session_state.min_interval_minutes, step=1, key='sidebar_min_interval_input')
    # 确保最大间隔大于最小间隔
    min_int_val = int(min_interval_minutes_input) if isinstance(min_interval_minutes_input, (int, float)) else 1 # 安全转换
    max_interval_minutes_input = st.number_input("最大常规提示音间隔 (分钟):", min_value=min_int_val + 1, value=st.session_state.max_interval_minutes, step=1, key='sidebar_max_interval_input')
    total_duration_minutes_input = st.number_input("总运行时长 (分钟，常规提示音在此时间后停止):", min_value=1, value=st.session_state.total_duration_minutes, step=5, key='sidebar_total_duration_input')
    final_duration_seconds_input = st.number_input("结束提示音播放时长 (秒):", min_value=5, value=st.session_state.final_duration_seconds, step=10, key='sidebar_final_duration_input')

    # 音量调节 (从 session state 加载值)
    volume_control_input = st.slider("音量调节:", 0.0, 1.0, st.session_state.volume_control, 0.01, key='sidebar_volume_input')

    # --- 将当前的配置保存到 session state ---
    # 直接保存用户输入的字符串，不在这里转换为绝对路径
    st.session_state.regular_sound_path = regular_sound_path_input
    st.session_state.final_sound_path = final_sound_path_input
    st.session_state.min_interval_minutes = min_interval_minutes_input
    st.session_state.max_interval_minutes = max_interval_minutes_input
    st.session_state.total_duration_minutes = total_duration_minutes_input
    st.session_state.final_duration_seconds = final_duration_seconds_input
    st.session_state.volume_control = volume_control_input

    st.markdown("---") # 分隔线
    st.markdown("[学习法视频](https://www.bilibili.com/video/BV1naLozQEBq/?spm_id_from=333.1007.tianma.6-4-22.click&vd_source=18f6d720bb29eddd4e2fb962fd7d9535)")


# --- 文件存在性检查 (主区域，更醒目) ---
# 检查配置中保存的路径对应的文件是否存在（使用转换后的绝对路径）
regular_path_session = st.session_state.get('regular_sound_path')
final_path_session = st.session_state.get('final_sound_path')

# 将 session_state 中保存的路径转换为基于脚本目录的绝对路径进行检查
resolved_regular_path_session = get_absolute_path_relative_to_script(regular_path_session)
resolved_final_path_session = get_absolute_path_relative_to_script(final_path_session)

# 检查转换后的路径是否存在且有效
files_exist_session = (resolved_regular_path_session is not None) and os.path.exists(resolved_regular_path_session) and \
                      (resolved_final_path_session is not None) and os.path.exists(resolved_final_path_session)


# 只有在非运行状态下才显示文件不存在错误，避免运行时覆盖线程状态
# 使用 thread_status 来更准确判断是否是“运行中”或“已结束但未清理”的状态
thread_current_status_check = st.session_state.status_data.get('thread_status', 'idle')
if thread_current_status_check in ['idle', 'finished']: # 只在空闲或已完成状态显示文件错误
    # 只有当用户输入了路径但文件不存在或路径无效时才显示错误
    if regular_path_session and not regular_file_valid_and_exists:
        st.error(f"错误：常规提示音文件 '{regular_path_session}' (实际检查: '{resolved_regular_path_session if resolved_regular_path_session else '路径无效或为空'}') 不存在。请检查侧边栏的路径。")
    if final_path_session and not final_file_valid_and_exists:
        st.error(f"错误：结束提示音文件 '{final_path_session}' (实际检查: '{resolved_final_path_session if resolved_final_path_session else '路径无效或为空'}') 不存在。请检查侧边栏的路径。")


# --- 控制按钮 (主区域) ---
st.header("控制")

col1, col2, col3, col4 = st.columns(4)

# 获取线程的实时状态来控制按钮可用性
thread_current_status = st.session_state.status_data.get('thread_status', 'idle')

# 开始计时按钮
with col1:
    # 只有当线程状态是 'idle' 或 'finished' 且 文件路径有效且文件存在时，开始按钮才可用
    # 注意这里 files_exist_session 已经是基于转换后的绝对路径检查的结果
    can_start = (thread_current_status == 'idle' or thread_current_status == 'finished') and files_exist_session
    if st.button("开始计时", disabled=not can_start):
        # 启动新任务前的状态清理和设置
        st.session_state.is_running = True # UI 层面标记运行中
        st.session_state.is_paused = False # UI 层面标记非暂停
        st.session_state.log_messages = [] # 清空之前的日志
        st.session_state.time_records = [] # 清空之前的记录
        # 创建新的事件对象，确保是未设置状态
        st.session_state.stop_event = threading.Event()
        st.session_state.pause_event = threading.Event()
        st.session_state.last_status = None # 清空上次任务的结束状态显示

        # --- 初始化本次运行的实时状态数据 ---
        st.session_state.status_data = {
            'elapsed_time': 0.0, # 实际运行时间从0开始
            'remaining_time': st.session_state.total_duration_minutes * 60.0, # 初始剩余时间为总时长
            'play_count': 0,
            'current_status': '正在启动...', # 告知用户 UI 正在启动
            'thread_status': 'starting', # 告知线程是新启动
            'start_time': time.time(), # 记录任务开始的系统时间戳
            'paused_duration': 0.0, # 累计暂停时长从0开始
            'pause_start_time': None, # 没有当前暂停
            'current_pause_duration_display': 0.0 # 实时暂停时长显示为0
        }

        # --- 在传递路径给线程前，将其转换为基于脚本目录的绝对路径 ---
        regular_sound_path_for_thread = get_absolute_path_relative_to_script(st.session_state.regular_sound_path)
        final_sound_path_for_thread = get_absolute_path_relative_to_script(st.session_state.final_sound_path)

        # --- 进行文件有效性和存在性检查 ---
        # 如果文件无效或不存在，显示错误并设置状态，然后退出当前按钮逻辑，但不使用 return
        file_error_message = None # 存储文件错误信息

        if not regular_sound_path_for_thread or not os.path.exists(regular_sound_path_for_thread):
             file_error_message = f"启动错误：常规提示音文件 '{st.session_state.regular_sound_path}' 无效或不存在 (实际检查: '{regular_sound_path_for_thread if regular_sound_path_for_thread else '路径无效或为空'}')。"
             st.error(file_error_message + " 请检查侧边栏的路径设置。")
             st.session_state.log_messages.append(file_error_message)
             st.session_state.status_data['current_status'] = '启动失败: 文件未找到或路径无效'
             st.session_state.status_data['thread_status'] = 'idle' # 启动失败，回到空闲
             st.session_state.is_running = False
             # 不在这里调用 st.rerun() 或 return

        elif not final_sound_path_for_thread or not os.path.exists(final_sound_path_for_thread):
             file_error_message = f"启动错误：结束提示音文件 '{st.session_state.final_sound_path}' 无效或不存在 (实际检查: '{final_sound_path_for_thread if final_sound_path_for_thread else '路径无效或为空'}')。"
             st.error(file_error_message + " 请检查侧边栏的路径设置。")
             st.session_state.log_messages.append(file_error_message)
             st.session_state.status_data['current_status'] = '启动失败: 文件未找到或路径无效'
             st.session_state.status_data['thread_status'] = 'idle' # 启动失败，回到空闲
             st.session_state.is_running = False
             # 不在这里调用 st.rerun() 或 return


        # --- 如果文件检查通过，则创建并启动线程 ---
        # 只有当 file_error_message 仍然是 None 时，表示没有文件错误
        if file_error_message is None:
            st.session_state.log_messages.append("文件路径检查通过，正在启动线程...") # 添加日志
            st.session_state.status_data['current_status'] = '正在启动线程...' # 更新状态

            # 创建并启动线程，传递转换后的绝对路径
            st.session_state.timer_thread = threading.Thread(
                target=run_audio_timer,
                args=(
                    st.session_state.min_interval_minutes,
                    st.session_state.max_interval_minutes,
                    regular_sound_path_for_thread, # <--- 使用转换后的绝对路径
                    st.session_state.total_duration_minutes,
                    final_sound_path_for_thread,   # <--- 使用转换后的绝对路径
                    st.session_state.final_duration_seconds,
                    st.session_state.volume_control,
                    st.session_state.log_messages, # 传递日志列表 (列表是可变对象，线程中修改会反映到主线程)
                    st.session_state.time_records, # 传递记录列表 (同上)
                    st.session_state.stop_event, # 传递停止事件
                    st.session_state.pause_event, # 传递暂停事件
                    st.session_state.status_data # 传递状态字典 (同上)
                )
            )
            st.session_state.timer_thread.start()
            # 启动后立即重新运行以更新UI显示状态，状态会从 'starting' 变为 'running'
            # 这个 rerun 是为了让 UI 立即反映线程状态的改变并进入刷新循环
            st.rerun()
        # else: # 如果有文件错误，就什么也不做，让 Streamlit 自然地结束当前的 rerun，显示错误
            # 错误消息和状态已经在上面的 if/elif 块中设置了


# 结束计时按钮
with col2:
    # 只有当线程状态不是 'idle' 或 'finished' 时，结束按钮才可用 (表示正在运行、暂停、启动或结束过程中)
    can_end = thread_current_status not in ['idle', 'finished']
    if st.button("结束计时", disabled=not can_end):
        # 告诉线程停止
        st.session_state.stop_event.set()
        # 如果当前是暂停状态，也清除暂停标志，确保线程能及时看到停止信号并退出暂停等待
        if st.session_state.is_paused: # 检查 UI 标志即可
             st.session_state.pause_event.clear()
             st.session_state.is_paused = False # UI 标记不再暂停状态

        st.session_state.log_messages.append(f"\n--- 用户请求结束于 {time.strftime('%Y-%m-%d %H:%M:%S')} ---") # 立即添加结束日志
        # 更新 UI 显示状态，告诉用户正在结束
        # 线程最终会更新 thread_status 和 current_status 到 stopping/stopped/finished
        st.session_state.status_data['current_status'] = "接收到结束请求，正在终止..."
        st.session_state.status_data['thread_status'] = 'stopping' # 标记线程状态为 stopping
        # Streamlit 会在下次 rerun 时检测到线程结束并进行 cleanup
        st.rerun() # 强制刷新 UI 显示结束请求状态

# 暂停计时按钮
with col3:
    # 只有当线程实际状态是 'running' 时，暂停按钮才可用
    can_pause = thread_current_status == 'running'
    if st.button("暂停计时", disabled=not can_pause):
        # 告诉线程暂停
        st.session_state.pause_event.set()
        st.session_state.is_paused = True # UI 标记为暂停状态
        st.session_state.log_messages.append(f"\n--- 用户请求暂停于 {time.strftime('%Y-%m-%d %H:%M:%S')} ---") # 立即添加暂停日志
        # 线程会在检测到 pause_event 后自己更新 status_data['current_status'] 和 ['thread_status'] 为 paused
        # UI 状态描述将由下面的显示逻辑根据 thread_status 来决定
        st.rerun() # 强制刷新 UI 显示暂停状态

# 继续计时按钮
with col4:
    # 只有当线程实际状态是 'paused' 时，继续按钮才可用
    can_continue = thread_current_status == 'paused'
    if st.button("继续计时", disabled=not can_continue):
        # 告诉线程继续
        st.session_state.pause_event.clear()
        st.session_state.is_paused = False # UI 标记为非暂停状态
        st.session_state.log_messages.append(f"\n--- 用户请求继续于 {time.strftime('%Y-%m-%d %H:%M:%S')} ---") # 立即添加继续日志
        # 线程会在检测到 pause_event.clear() 后自己更新 status_data['current_status'] 和 ['thread_status'] 为 running
        # UI 状态描述将由下面的显示逻辑根据 thread_status 来决定
        st.rerun() # 强制刷新 UI 显示继续状态


# --- 实时状态显示 (主区域) ---
st.header("实时状态")

# 从 status_data 中读取所有需要显示的信息
thread_status = st.session_state.status_data.get('thread_status', 'idle')
current_status_text_from_thread = st.session_state.status_data.get('current_status', 'N/A')
elapsed_time_sec = st.session_state.status_data.get('elapsed_time', 0.0)
remaining_time_sec = st.session_state.status_data.get('remaining_time', 0.0)
play_count = st.session_state.status_data.get('play_count', 0)
paused_duration_cumulative_sec = st.session_state.status_data.get('paused_duration', 0.0)
current_pause_duration_realtime_sec = st.session_state.status_data.get('current_pause_duration_display', 0.0)

# --- 根据 thread_status 决定最终显示的状态文本和时间/计数数值 ---
display_status_text = "未知状态" # 默认值
display_elapsed_time_sec = elapsed_time_sec
display_remaining_time_sec = remaining_time_sec
display_play_count = play_count
display_paused_duration_sec = paused_duration_cumulative_sec # 默认显示累计暂停时长

if thread_status == 'idle':
    # 线程处于空闲状态 (刚启动或上次任务已处理完并清理)
    if st.session_state.last_status:
        display_status_text = f"上次运行状态: {st.session_state.last_status}"
    else:
        display_status_text = "空闲，等待开始..."
    # 在空闲状态下，时间/计数显示为0或总时长
    display_elapsed_time_sec = 0.0
    display_play_count = 0
    display_paused_duration_sec = 0.0
    # 剩余时间显示配置的总时长，如果配置存在
    if 'total_duration_minutes' in st.session_state:
         display_remaining_time_sec = st.session_state.total_duration_minutes * 60.0
    else:
         display_remaining_time_sec = 0.0 # 如果配置也不存在，显示0

elif thread_status == 'paused':
    # 线程处于暂停状态，显示实时暂停时长
    display_status_text = f"已暂停 ({format_seconds_to_minutes_seconds(current_pause_duration_realtime_sec)})"
    # paused_duration_cumulative_sec 已经是累计值

# 对于所有其他状态 ('starting', 'running', 'stopping', 'finishing_regular', 'finishing', 'finished')
else:
    # 直接显示线程报告的 current_status 文本
    display_status_text = current_status_text_from_thread
    # 线程在这些状态下会更新 elapsed_time, remaining_time, play_count, paused_duration


# --- 显示所有状态信息 ---
st.write(f"**当前状态:** {display_status_text}")
st.write(f"**实际已运行时间:** {format_seconds_to_minutes_seconds(display_elapsed_time_sec)}")
st.write(f"**常规计时阶段剩余:** {format_seconds_to_minutes_seconds(display_remaining_time_sec)}")
st.write(f"**常规提示音已响次数:** {display_play_count}")
st.write(f"**累计暂停时长:** {format_seconds_to_minutes_seconds(display_paused_duration_sec)}")


# --- 自动刷新逻辑和线程结束处理 ---
# 检查 Streamlit UI 是否认为程序在运行 (通过检查 thread_status 不是 idle 或 finished)
is_actively_running = thread_current_status not in ['idle', 'finished']

# 检查 Streamlit UI 认为它在运行 (is_running == True)，但线程已经死了 (timer_thread is None or not is_alive())
# 并且线程内部状态已经标记为 'finished'
# 这个块处理线程任务完成或停止后的 UI 清理和重置
if st.session_state.is_running and thread_current_status == 'finished':
     # 线程已完成或被停止，且线程自己在 finally 里将 status_data['thread_status'] 设为 'finished'

     # --- 进行 Streamlit UI 状态的全面重置以回到空闲状态 ---
     st.session_state.is_running = False # UI 不再标记运行中
     st.session_state.is_paused = False # UI 不再标记暂停
     st.session_state.timer_thread = None # 清理线程对象，确保下次可以重新创建

     # 从 status_data 中获取线程写入的最终状态和时间信息
     final_status_message = st.session_state.status_data.get('current_status', '任务结束')
     final_elapsed_time = st.session_state.status_data.get('elapsed_time', 0.0)
     final_paused_duration = st.session_state.status_data.get('paused_duration', 0.0)

     st.session_state.last_status = final_status_message # 存储最终状态，用于下次启动前的空闲显示

     # 清理事件对象，创建新的，为下次运行做准备
     st.session_state.stop_event = threading.Event()
     st.session_state.pause_event = threading.Event()

     # Log final messages
     # 检查最后几条日志，避免重复添加结束标记
     # 取日志列表的后20条进行检查，避免列表过长
     if "--- 任务处理结束于" not in "\n".join(st.session_state.log_messages[-20:]):
         st.session_state.log_messages.append(f"--- 任务处理结束于 {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
         st.session_state.log_messages.append(f"最终状态: {final_status_message}")
         st.session_state.log_messages.append(f"最终实际运行时间: {format_seconds_to_minutes_seconds(final_elapsed_time)}")
         st.session_state.log_messages.append(f"总累计暂停时长: {format_seconds_to_minutes_seconds(final_paused_duration)}")

     # 将 status_data 中的关键字段重置为初始的空闲值，确保 UI 在线程结束后能干净地回到初始状态。
     # 注意：status_data 中的这些值在上面已经读取并用于最终日志/显示了，这里只是重置它们以便下次干净启动
     st.session_state.status_data['thread_status'] = 'idle' # <-- 重设为 idle
     st.session_state.status_data['current_status'] = '空闲' # 匹配 thread_status
     st.session_state.status_data['elapsed_time'] = 0.0
     # st.session_state.status_data['remaining_time'] = 0.0 # 这个在 idle 状态显示总时长，所以不用在这里重设为0
     st.session_state.status_data['play_count'] = 0
     st.session_state.status_data['paused_duration'] = 0.0
     st.session_state.status_data['pause_start_time'] = None
     st.session_state.status_data['current_pause_duration_display'] = 0.0

     # 任务结束且清理完成后，强制刷新 UI 回到空闲状态
     # 这个 rerun 是必须的，它确保 UI 状态在线程结束后立即更新
     st.rerun()


elif is_actively_running and st.session_state.timer_thread and st.session_state.timer_thread.is_alive():
    # 线程仍在运行 (包括暂停，stopping, finishing等)，说明任务还在进行中
    # 为了实时更新显示，每隔一段时间强制 Streamlit 重新运行整个脚本
    # 注意：Streamlit 0.84+ 可以使用 st.script_runner.script_requests.RerunData(rerun_data) 或 st.experimental_rerun()
    # 但 time.sleep() + st.rerun() 是更通用的方式，确保 Streamlit 有足够时间读取线程更新的状态
    time.sleep(0.5) # 每隔0.5秒刷新一次 UI
    st.rerun() # 强制 Streamlit 重新运行脚本


# --- 日志输出 (折叠栏) ---
st.header("日志")
log_text = "\n".join(st.session_state.log_messages)
# 使用 st.expander 创建折叠栏
# expanded=True 表示默认展开，False 表示默认折叠
with st.expander("查看程序日志", expanded=True):
    # 使用 markdown 格式化日志，支持换行，并保持 pre-formatted 样式
    # height 参数可以控制显示区域的高度
    st.markdown(f"```\n{log_text}\n```", help="程序输出日志")


# --- 时间记录 (主区域) ---
st.header("常规提示音响起时间记录")
if st.session_state.time_records:
    formatted_records = [
        datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        for ts in st.session_state.time_records
    ]
    # 使用 markdown 显示列表，每个元素一行
    record_list_markdown = "\n".join([f"- {rec}" for rec in formatted_records])
    st.markdown(record_list_markdown)
else:
    st.write("暂无时间记录。")