# 学习函数.py (修改后 - v3: 使用传递进来的绝对路径)
import time
import random
import os
import pygame
import threading
import datetime
import math # 导入 math 用于 floor

# 将核心逻辑封装在一个函数中
# 这个函数将在一个单独的线程中运行
def run_audio_timer(
    min_interval_minutes,
    max_interval_minutes,
    regular_sound_path, # 现在这里会接收到绝对路径
    total_duration_minutes,
    final_sound_path,   # 现在这里会接收到绝对路径
    final_duration_seconds,
    volume_control,
    log_list, # 用于将日志传递给调用者 (Streamlit)
    time_records, # 用于将时间记录传递给调用者 (Streamlit)
    stop_event, # 用于接收停止信号 (threading.Event)
    pause_event, # 用于接收暂停信号 (threading.Event)
    status_data # 用于存储实时状态数据的字典
):
    """
    运行音频计时器逻辑。在单独的线程中调用。

    参数:
        min_interval_minutes (int): 最小常规提示音间隔 (分钟).
        max_interval_minutes (int): 最大常规提示音间隔 (分钟).
        regular_sound_path (str): 常规提示音文件 **绝对** 路径.
        total_duration_minutes (int): 常规提示音总运行时长 (分钟).
        final_sound_path (str): 结束提示音文件 **绝对** 路径.
        final_duration_seconds (int): 结束提示音持续时长 (秒).
        volume_control (float): 音量 (0.0 - 1.0).
        log_list (list): 用于存储日志消息的列表. (会在线程中被修改)
        time_records (list): 用于存储常规提示音响起的时间戳的列表. (会在线程中被修改)
        stop_event (threading.Event): 用于接收外部停止信号的事件对象. (会在主线程中被设置，线程中被检查)
        pause_event (threading.Event): 用于接收外部暂停信号的事件对象. (会在主线程中被设置/清除，线程中被检查/等待)
        status_data (dict): 用于存储并向主线程传递实时状态的字典。 (会在线程中被修改)
                         应包含 'elapsed_time', 'remaining_time', 'play_count', 'current_status', 'start_time',
                         'thread_status', 'paused_duration', 'pause_start_time', 'current_pause_duration_display' 键。

    返回:
        str: 表示任务完成状态的字符串 ("completed", "stopped", "error").
    """

    # --- 将配置转换为秒 ---
    min_interval_seconds = min_interval_minutes * 60
    max_interval_seconds = max_interval_minutes * 60
    total_duration_seconds = total_duration_minutes * 60

    # 初始化状态变量
    status = "error" # 默认返回状态
    regular_sound = None
    final_sound = None

    # 从 status_data 中读取当前状态，以支持从暂停恢复
    # 这些值是主线程传递进来的，包含了上次运行/暂停时的状态
    elapsed_time = status_data.get('elapsed_time', 0.0) # 实际运行时间 (从上次结束或暂停时开始)
    paused_duration = status_data.get('paused_duration', 0.0) # 累计暂停时长 (从上次结束或暂停时开始)
    pause_start_time = status_data.get('pause_start_time', None) # 当前暂停的开始系统时间 (如果从暂停中恢复，这里会有值)
    start_time = status_data.get('start_time') # 任务开始的系统时间 (第一次运行时在主线程设置)

    # 记录日志到 log_list
    # 首次启动线程时才记录这些初始信息 (通过检查 thread_status 是否是 'starting')
    if status_data.get('thread_status') == 'starting':
        log_list.append("--------------------")
        log_list.append(f"程序已启动。常规提示音将在累计运行 {total_duration_minutes} 分钟后停止。")
        # 记录使用的文件路径，方便调试
        log_list.append(f"常规提示音文件: '{regular_sound_path}'")
        log_list.append(f"结束提示音文件: '{final_sound_path}'")
        log_list.append(f"在此期间，每隔 {min_interval_minutes}-{max_interval_minutes} 分钟会响起常规提示音。")
        log_list.append("闭眼休息10秒")
        log_list.append(f"常规提示音停止后，将播放结束提示音，持续 {final_duration_seconds} 秒，然后程序结束。")
        log_list.append("休息20分钟，补充钠钾离子，推荐喝电解质饮料。可以买那种电解质粉，加水冲泡后喝，性价比会高很多。")
        log_list.append("--------------------")
        status_data['thread_status'] = 'running' # 启动后立即设置为 running
        status_data['current_status'] = "正在运行..." # 更新初始状态描述


    try:
        # --- 检查文件是否存在 (在线程内部再次检查，更安全) ---
        # 注意：这里的路径已经是主线程转换并传递进来的绝对路径
        # 这里也增加对 None 或空字符串的检查，虽然主线程已经做了，但多一层防御总是好的
        if not regular_sound_path or not os.path.exists(regular_sound_path):
            msg = f"错误：线程内部找不到常规提示音文件 '{regular_sound_path}'。"
            log_list.append(msg)
            status_data['current_status'] = msg # 更新实时状态
            status = "error"
            status_data['thread_status'] = 'finished' # 标记线程结束
            return status # 立即退出线程

        if not final_sound_path or not os.path.exists(final_sound_path):
            msg = f"错误：线程内部找不到结束提示音文件 '{final_sound_path}'。"
            log_list.append(msg)
            status_data['current_status'] = msg # 更新实时状态
            status = "error"
            status_data['thread_status'] = 'finished' # 标记线程结束
            return status # 立即退出线程


        # --- 初始化 pygame mixer ---
        try:
             # 只有当 mixer 未初始化时才初始化，避免从暂停恢复时重复初始化
             if not pygame.mixer.get_init():
                 pygame.mixer.init()
                 log_list.append("pygame mixer 初始化成功。")
             # else:
                 # log_list.append("pygame mixer 已初始化。") # 从暂停恢复时会打印这个

        except pygame.error as e:
            msg = f"错误：无法初始化 pygame mixer: {e}"
            log_list.append(msg)
            status_data['current_status'] = msg # 更新实时状态
            status = "error"
            status_data['thread_status'] = 'finished' # 标记线程结束
            return status # 立即退出线程

        # --- 提前加载音频文件 ---
        try:
            # 如果音频对象已存在 (从暂停恢复)，则不重新加载
            # 这里加载为 Sound 对象，因为 Sound 更灵活，可以重复播放
            # mixer.music 适合播放背景音乐，Sound 适合短促的提示音
            if regular_sound is None: # 只有当对象未创建时才创建
                 regular_sound = pygame.mixer.Sound(regular_sound_path)
            if final_sound is None: # 只有当对象未创建时才创建
                 final_sound = pygame.mixer.Sound(final_sound_path)

            # 首次加载成功才记录日志
            if regular_sound is not None and final_sound is not None and "音频文件加载成功" not in "\n".join(log_list[-5:]): # 检查最近几条日志
                 log_list.append("音频文件加载成功。")

        except pygame.error as e:
            msg = f"错误：无法加载音频文件: {e}"
            log_list.append(msg)
            status_data['current_status'] = msg # 更新实时状态
            # 清理一下可能已经初始化的 mixer
            if pygame.mixer.get_init():
                 pygame.mixer.quit()
                 log_list.append("pygame mixer 已关闭 (加载错误时)。")
            status = "error"
            status_data['thread_status'] = 'finished' # 标记线程结束
            return status # 立即退出线程

        # --- 设置音量 ---
        # 每次线程启动或恢复时都设置一次音量
        if 0.0 <= volume_control <= 1.0:
            # 确保音频对象已经成功创建
            if regular_sound:
                regular_sound.set_volume(volume_control)
            if final_sound:
                final_sound.set_volume(volume_control)
            if f"音量设置为 {volume_control:.2f}" not in "\n".join(log_list[-5:]): # 避免频繁重复记录
                 log_list.append(f"音量设置为 {volume_control:.2f} ({volume_control*100:.0f}%)。")
        else:
            if "警告：配置的音量值" not in "\n".join(log_list[-5:]): # 避免频繁重复记录
                 log_list.append(f"警告：配置的音量值 {volume_control} 不在 0.0 到 1.0 的有效范围内。将使用默认音量。")
                 # 使用默认音量 (通常是 1.0)，但要确保音频对象存在
                 if regular_sound:
                     regular_sound.set_volume(1.0)
                 if final_sound:
                     final_sound.set_volume(1.0)


        last_status_update_time = time.time() # 用于控制状态更新频率

        # 主循环：只要没有收到停止信号
        # 注意：这里的循环条件只检查停止信号，达到总时长在循环内部判断并break
        while not stop_event.is_set():

            # 计算当前的实际运行时间
            current_time = time.time() # 总是获取当前的系统时间

            # --- 检查暂停状态 ---
            if pause_event.is_set():
                # 如果是刚刚进入暂停状态
                if status_data.get('thread_status') != 'paused':
                    status_data['thread_status'] = 'paused'
                    status_data['current_status'] = "已暂停..."
                    # 记录本次暂停开始的系统时间
                    pause_start_time = current_time # 使用当前的系统时间作为暂停开始时间
                    status_data['pause_start_time'] = pause_start_time
                    log_list.append(f"\n--- 计时已暂停于 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time))} ---")
                    # 清除实时的暂停时长显示，直到进入暂停等待循环
                    status_data['current_pause_duration_display'] = 0.0
                    # 停止当前可能还在播放的常规音
                    pygame.mixer.stop()


                # --- 暂停等待循环：在这里实时更新暂停时长 ---
                last_pause_display_update_time = current_time # 用于控制暂停时长更新频率
                while pause_event.is_set() and not stop_event.is_set():
                    current_time_in_pause = time.time()
                    # 当前这次暂停已经持续的时长
                    current_pause_duration_in_progress = current_time_in_pause - pause_start_time

                    # 实时更新暂停时长显示 (每隔一定时间)
                    if current_time_in_pause - last_pause_display_update_time > 0.5: # 每0.5秒更新
                        status_data['current_pause_duration_display'] = current_pause_duration_in_progress
                        last_pause_display_update_time = current_time_in_pause

                    time.sleep(0.1) # 短暂等待并检查标志

                # 暂停等待结束，检查是停止还是继续
                if stop_event.is_set():
                    log_list.append("\n收到停止信号，暂停中中止。")
                    status_data['current_status'] = "已接收停止信号，正在终止..."
                    status_data['thread_status'] = 'stopping' # 标记正在停止
                    status = "stopped" # 设置返回状态
                    break # 跳出主循环 (包括暂停等待循环和外层 while 循环)

                # 如果是因为暂停事件被清除了 (继续)
                if not pause_event.is_set(): # 此时 stop_event 也不是 set
                    # 计算本次暂停的时长并累加到总累计时长
                    # pause_start_time 在进入暂停时记录，现在用当前时间减去它
                    current_pause_duration = time.time() - pause_start_time
                    paused_duration += current_pause_duration # 累加到总暂停时长
                    status_data['paused_duration'] = paused_duration
                    status_data['pause_start_time'] = None # 清除本次暂停开始时间
                    status_data['current_pause_duration_display'] = 0.0 # 清除实时暂停时长显示
                    status_data['thread_status'] = 'running' # 标记恢复运行
                    log_list.append(f"\n--- 计时已恢复于 {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
                    log_list.append(f"本次暂停时长: {current_pause_duration:.2f} 秒 ({current_pause_duration/60:.2f} 分钟)")
                    log_list.append(f"累计暂停时长: {paused_duration:.2f} 秒 ({paused_duration/60:.2f} 分钟)")
                    status_data['current_status'] = "正在运行..." # 恢复运行状态描述
                    # 更新 start_time 以便从恢复的时间点开始计算elapsed_time (或者更简单：保持start_time不变，elapsed_time计算时减去paused_duration)
                    # 我们选择保持 start_time 不变，计算 elapsed_time = (current_time - start_time) - paused_duration


            # --- 如果没有暂停且没有停止，则正常运行逻辑 ---
            # 计算实际运行时间 (排除暂停时间)
            # 只有在线程状态是 'running' 时，elapsed_time 和 remaining_time 才应该实时更新
            if status_data.get('thread_status') == 'running':
                 current_time = time.time() # 再次获取当前时间，确保精确
                 actual_elapsed_time = (current_time - start_time) - paused_duration
                 remaining_regular_time = total_duration_seconds - actual_elapsed_time # 线程内部计算的剩余时间

                 # --- 实时更新状态数据 (每隔一定时间更新一次，避免过于频繁) ---
                 if current_time - last_status_update_time > 0.5: # 每0.5秒更新一次状态
                     status_data['elapsed_time'] = actual_elapsed_time # 更新实际运行时间
                     status_data['remaining_time'] = max(0.0, remaining_regular_time) # 剩余时间不能为负
                     last_status_update_time = current_time
                     # Streamlit 主线程通过 st.rerun() 来读取这些更新


                 # 检查是否已达到常规提示音的总运行时长 (使用实际运行时间)
                 if actual_elapsed_time >= total_duration_seconds:
                     log_list.append("常规提示音总运行时长已达到。准备播放结束提示音。")
                     status_data['current_status'] = "常规计时结束，准备结束音..."
                     status_data['thread_status'] = 'finishing_regular' # 标记常规阶段结束
                     # 确保最终的时间数据在跳出循环前更新
                     status_data['elapsed_time'] = total_duration_seconds # 达到总时长
                     status_data['remaining_time'] = 0.0
                     break # 跳出 while 循环，进入结束处理阶段

                 # --- 计算下一个随机等待时间 ---
                 # 只有在还有剩余常规时间的情况下才计算和等待
                 if remaining_regular_time > 0:
                     wait_seconds = random.uniform(min_interval_seconds, max_interval_seconds)
                     # 实际等待时间取计算出的随机时间和剩余常规时间中的最小值，确保不会超过总时长
                     actual_sleep_duration = min(wait_seconds, remaining_regular_time)
                 else:
                     # 如果没有剩余常规时间，不应该再等待播放常规音了
                     actual_sleep_duration = 0


                 # 如果需要等待 (actual_sleep_duration > 0)
                 if actual_sleep_duration > 0:
                     # 报告等待时间和剩余总时间
                     log_list.append(f"\n--------------------")
                     log_list.append(f"当前实际运行: {actual_elapsed_time:.2f} 秒 ({actual_elapsed_time/60:.2f} 分钟)")
                     log_list.append(f"常规提示音阶段剩余时间: {remaining_regular_time:.2f} 秒 ({remaining_regular_time/60:.2f} 分钟)")
                     log_list.append(f"下一个常规提示音将在约 {actual_sleep_duration:.2f} 秒 ({actual_sleep_duration/60:.2f} 分钟) 后尝试响起。")
                     log_list.append(f"当前系统时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time))}")
                     log_list.append(f"--------------------")
                     # 更新状态描述，显示等待时长
                     status_data['current_status'] = f"等待常规提示音... ({math.floor(actual_sleep_duration)} 秒)"


                     # --- 分小步等待，并随时检查停止和暂停事件 ---
                     sleep_interval = 0.1 # 每隔0.1秒检查一次标志
                     slept_duration = 0
                     wait_start_time = time.time() # 记录本次等待开始的系统时间
                     while slept_duration < actual_sleep_duration and not stop_event.is_set() and not pause_event.is_set():
                         # 根据本次等待开始时间计算已经等待的时长
                         slept_duration = time.time() - wait_start_time
                         # 如果已经睡够了，直接 break (避免微小的时间差导致多睡)
                         if slept_duration >= actual_sleep_duration:
                              break

                         # 计算下一次实际睡眠时长 (不能超过剩余的等待时长)
                         current_sleep_step = min(sleep_interval, actual_sleep_duration - slept_duration)
                         time.sleep(current_sleep_step)

                         # 在等待过程中也实时更新时间信息 (只有在运行状态下)
                         current_time_inner = time.time()
                         actual_elapsed_time_inner = (current_time_inner - start_time) - paused_duration
                         remaining_regular_time_inner = total_duration_seconds - actual_elapsed_time_inner

                         # 检查是否需要更新状态数据
                         if current_time_inner - last_status_update_time > 0.5:
                             status_data['elapsed_time'] = actual_elapsed_time_inner
                             status_data['remaining_time'] = max(0.0, remaining_regular_time_inner)
                             last_status_update_time = current_time_inner
                             # 更新状态描述，显示剩余等待时长
                             status_data['current_status'] = f"等待常规提示音... ({max(0, math.floor(actual_sleep_duration - slept_duration))} 秒)"


                     # --- 内层等待循环结束 ---
                     # 检查是否是因为停止事件而被唤醒
                     if stop_event.is_set():
                         log_list.append("\n收到停止信号，常规计时阶段等待中中止。")
                         status_data['current_status'] = "已接收停止信号，正在终止..."
                         status_data['thread_status'] = 'stopping'
                         status = "stopped" # 设置返回状态
                         break # 退出外层 while 循环

                     # 如果是因为暂停事件而被唤醒，外层 while 循环会继续，并在下一轮开始时处理暂停逻辑 (上面已经处理)

                     # 如果等待完成（且没有停止或暂停），再次检查是否已超过总时长 (双重保险)
                     # 重新计算实际运行时间，确保准确
                     current_time_after_sleep = time.time()
                     actual_elapsed_time_after_sleep = (current_time_after_sleep - start_time) - paused_duration
                     if actual_elapsed_time_after_sleep >= total_duration_seconds:
                          log_list.append("等待后检查：常规提示音总运行时长已达到，跳出循环。")
                          status_data['current_status'] = "常规计时结束 (等待后检查)..."
                          status_data['thread_status'] = 'finishing_regular'
                          # 确保最终的时间数据在跳出循环前更新
                          status_data['elapsed_time'] = total_duration_seconds
                          status_data['remaining_time'] = 0.0
                          break # 确保跳出外层 while 循环


                 # 如果等待时间 actual_sleep_duration 为0 (说明剩余常规时间非常少，直接播放或跳过)
                 # 或者 等待完成且未达到总时长且未停止/暂停，播放常规提示音
                 # 只有在线程状态是 'running' 时才播放，防止从暂停恢复后立即响或在结束流程中响
                 if status_data.get('thread_status') == 'running' and not stop_event.is_set() and not pause_event.is_set():
                      # 在播放常规提示音前，再次检查是否已超过常规总时长
                      current_time_before_play = time.time()
                      actual_elapsed_time_before_play = (current_time_before_play - start_time) - paused_duration
                      if actual_elapsed_time_before_play >= total_duration_seconds:
                          log_list.append("播放前检查：常规提示音总运行时长已达到，跳过播放常规提示音。")
                          status_data['current_status'] = "常规计时结束 (播放前检查)..."
                          status_data['thread_status'] = 'finishing_regular'
                          status_data['elapsed_time'] = total_duration_seconds
                          status_data['remaining_time'] = 0.0
                          break # 跳出外层 while 循环

                      # 播放常规提示音
                      log_list.append(f"时间到！播放常规提示音 '{os.path.basename(regular_sound_path)}'...")
                      status_data['current_status'] = "播放常规提示音..." # 更新状态
                      try:
                          # 使用 pygame.mixer.Sound.play() 是非阻塞的
                          if regular_sound: # 确保音频对象存在
                              regular_sound.play()
                              # 记录常规提示音响起的绝对时间戳
                              current_sound_time = time.time()
                              time_records.append(current_sound_time)
                              status_data['play_count'] += 1 # 增加播放次数
                              # log_list.append(f"常规提示音播放完毕 (通过 pygame)。") # pygame.Sound().play() 是非阻塞的，这句会立即打印

                              # 短暂等待，确保声音有机会播放出来，特别是对于很短的声音文件
                              # 避免因为声音文件损坏或极短导致 get_length() 返回 0 报错
                              sound_length = regular_sound.get_length()
                              if sound_length > 0:
                                  time.sleep(sound_length + 0.1) # 等待声音时长+一点缓冲
                              else:
                                   time.sleep(0.5) # 如果声音文件无效或极短，至少等待0.5秒


                          # 播放完毕后，状态描述会立即更新到下一个等待周期开始时的状态描述 (等待约 X 秒...)
                          # 下一轮循环开始会重新计算 elapsed_time 并更新状态

                      except pygame.error as e:
                          msg = f"播放常规音频时出错 (pygame)：{e}"
                          log_list.append(msg)
                          status_data['current_status'] = msg # 更新状态
                      except Exception as e:
                          msg = f"播放常规音频时发生未知错误：{e}"
                          log_list.append(msg)
                          status_data['current_status'] = msg # 更新状态

                 # 如果因为剩余时间不足导致 actual_sleep_duration 为0，且未达到总时长
                 # 例如 90分钟总时长，还剩5秒，min_interval=3分钟，max_interval=5分钟
                 # 计算出的随机等待可能是3分钟，但 actual_sleep_duration 会变成 5秒
                 # 等待5秒后，actual_elapsed_time 就达到了总时长，循环会在下一次检查时 break
                 # 如果 remaining_regular_time < min_interval_seconds, 并且等待结束后仍未达到 total_duration_seconds
                 # 那么实际等待时间 actual_sleep_duration 会是剩余时间，等待结束后刚好达到或超过总时长，循环会 break
                 # 看起来这个逻辑是安全的。

            # 如果线程状态不是 'running' (可能是 'paused' 或 'stopping' 等)，则跳过常规运行逻辑，只处理标志检查
            else:
                 # 线程处于暂停、启动、停止等状态，只需要短暂等待并让主循环检查标志
                 time.sleep(0.1) # 短暂等待

        # --- 外层 While 循环结束后的处理 (总运行时间已达到常规时长 或 收到了停止信号) ---

        # 停止所有可能还在播放的声音
        pygame.mixer.stop()
        log_list.append("停止所有正在播放的声音。")

        # 获取循环结束时的准确时间（系统时间）
        current_time_end_loop = time.time()
        # 计算最终的实际运行时间 (确保在线程结束前更新一次)
        # final_actual_elapsed_at_end_of_loop = (current_time_end_loop - start_time) - paused_duration
        # 此时 elapsed_time 应该已经是最终值 (total_duration_seconds 或停止时的值)

        # 只有在正常完成常规计时阶段时，才播放结束音
        # 检查是否是因为达到了总时长而退出循环 (thread_status 应该是 'finishing_regular')，而不是因为停止信号
        if status_data.get('thread_status') == 'finishing_regular' and not stop_event.is_set():
            log_list.append("\n====================")
            log_list.append(f"程序已运行达到设定的 {total_duration_minutes} 分钟常规时长。")
            log_list.append(f"开始播放结束提示音 '{os.path.basename(final_sound_path)}'，持续 {final_duration_seconds} 秒...")
            status_data['current_status'] = "播放结束提示音..." # 更新状态
            status_data['thread_status'] = 'finishing' # 标记正在播放结束音

            try:
                # 播放结束提示音
                # 如果需要精确控制时长，并且 final_sound_seconds 小于音频文件本身的长度，Sound 对象的 play 方法 with maxtime 参数是合适的
                # 如果 final_sound_seconds 大于等于音频文件本身的长度，音频会循环播放直到时间结束或被 stop
                # 如果只需要播放一次直到结束，直接 final_sound.play() 即可
                # 这里我们按需求使用 maxtime

                if final_sound: # 确保音频对象存在
                    log_list.append(f"正在播放结束提示音... ({final_duration_seconds} 秒)")
                    # 播放一次，并设置最大播放时长 (毫秒)
                    final_sound.play(loops=0, maxtime=final_duration_seconds * 1000)

                    # 等待指定的结束提示音时长，同时检查停止事件
                    end_sound_slept_duration = 0
                    sleep_interval = 0.5 # 结束音等待时可以稍微长一点检查标志
                    end_sound_start_time = time.time() # 记录结束音播放开始时间
                    while end_sound_slept_duration < final_duration_seconds and not stop_event.is_set():
                        # 计算已经等待的时长
                        end_sound_slept_duration = time.time() - end_sound_start_time

                        # 如果已经睡够了，直接 break
                        if end_sound_slept_duration >= final_duration_seconds:
                            break

                        # 计算下一次实际睡眠时长 (不能超过剩余的等待时长)
                        current_sleep_step = min(sleep_interval, final_duration_seconds - end_sound_slept_duration)
                        time.sleep(current_sleep_step)

                        # 结束音播放期间也可以更新一下状态 (可选，但可以显示倒计时)
                        # status_data['current_status'] = f"播放结束音... (剩余约 {max(0, final_duration_seconds - int(end_sound_slept_duration))} 秒)"

                    # 停止所有正在播放的声音 (确保结束音停止)
                    pygame.mixer.stop()

                    if not stop_event.is_set():
                        log_list.append(f"结束提示音播放完毕 ({final_duration_seconds} 秒)。")
                        status_data['current_status'] = "任务完成"
                        status = "completed" # 正常完成
                    else:
                        log_list.append(f"播放结束音期间收到停止信号，提前中止。")
                        status_data['current_status'] = "结束音播放期间中止"
                        status = "stopped" # 被用户停止
                else:
                    msg = "错误：结束音频对象未成功创建，无法播放结束音。"
                    log_list.append(msg)
                    status_data['current_status'] = msg
                    status = "error"


            except pygame.error as e:
                msg = f"播放结束音频时出错 (pygame)：{e}"
                log_list.append(msg)
                status_data['current_status'] = msg # 更新状态
                status = "error"
            except Exception as e:
                msg = f"播放结束音频时发生未知错误：{e}"
                log_list.append(msg)
                status_data['current_status'] = msg # 更新状态
                status = "error"

        # 如果是因为停止事件退出的常规循环 (且没有进入结束音播放阶段)
        elif stop_event.is_set():
             log_list.append("\n收到停止信号，程序中止。")
             # 如果状态已经是错误信息，保留它
             if not status_data['current_status'].startswith("错误"):
                 status_data['current_status'] = "任务已停止"
             status = "stopped" # 被用户停止

        else:
             # 未知情况退出循环，可能是逻辑错误或者在加载/初始化阶段出错
             # 如果 status_data['current_status'] 已经是错误信息，保留它
             if not status_data['current_status'].startswith("错误"):
                  msg = "\n未知情况导致循环退出或线程提前终止。"
                  log_list.append(msg)
                  status_data['current_status'] = msg # 更新状态
             # 如果 status 没有被前面的逻辑设置为 completed/stopped/error，则强制设置为 error
             if status not in ["completed", "stopped", "error"]:
                  status = "error"


    except Exception as e:
        # 捕获其他未预见的异常
        msg = f"程序运行过程中发生未捕获的异常: {e}"
        log_list.append(msg)
        status_data['current_status'] = msg # 更新状态
        status = "error" # 设置返回状态为 error


    finally:
        # --- 清理 pygame mixer ---
        # 只有在 mixer 被成功初始化过才尝试退出
        if pygame.mixer.get_init():
             pygame.mixer.quit()
             log_list.append("pygame mixer 已关闭。")
        log_list.append(f"当前系统时间 (结束): {time.strftime('%Y-%m-%d %H:%M:%S')}")
        log_list.append(f"任务结束处理完成。")

        # 确保 status_data['current_status'] 和 status_data['thread_status'] 反映最终状态
        # 优先保留错误信息或已设置的停止/完成状态
        if status_data['thread_status'] != 'finished': # 避免重复设置finished状态
             if status == "completed" and not status_data['current_status'].startswith("错误"):
                  status_data['current_status'] = "任务完成"
             elif status == "stopped" and not status_data['current_status'].startswith("错误"):
                  status_data['current_status'] = "任务已停止"
             elif status == "error" and not status_data['current_status'].startswith("错误"):
                  # 如果当前状态不是错误，并且最终状态是 error，设置一个通用错误信息
                  if status_data['current_status'] not in ['正在启动...', '已接收停止信号，正在终止...', '结束音播放期间中止', '任务已停止']:
                     status_data['current_status'] = "任务发生错误"
                  # 如果是启动错误，错误信息已经在前面设置了，保持不变

             status_data['thread_status'] = 'finished' # 标记线程内部状态为完成
             status_data['pause_start_time'] = None # 清除暂停开始时间
             status_data['current_pause_duration_display'] = 0.0 # 清除实时暂停时长显示

        # 返回最终状态
        return status