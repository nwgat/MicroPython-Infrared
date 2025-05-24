# NEC IR Receiver for Raspberry Pi Pico W with VS1838B or similar
#
# Connections:
# VS1838B VCC -> 3.3V (Pico Pin 36)
# VS1838B GND -> GND (Pico Pin 38 or any GND)
# VS1838B DATA/OUT -> GPIO Pin (e.g., GP15, Pico Pin 20)
#
# Note: The VS1838B output is active LOW.

import machine
import time
import rp2

# --- Configuration ---
IR_PIN_NUM = 15  # GPIO pin connected to the IR receiver's data pin

# --- NEC Protocol Timing Constants (in microseconds) ---
NEC_HDR_MARK = 9000
NEC_HDR_SPACE = 4500
NEC_BIT_MARK = 562
NEC_ONE_SPACE = 1688
NEC_ZERO_SPACE = 562
NEC_RPT_SPACE = 2250
NEC_STOP_MARK = 562 # Often not explicitly checked

TOLERANCE_US = 400 # Increased tolerance slightly

# Threshold for considering a pulse as initial idle time to be discarded
INITIAL_IDLE_THRESHOLD_US = 20000 # 20ms, much longer than any NEC signal component

class IRReceiver:
    def __init__(self, pin_num):
        self.pin = machine.Pin(pin_num, machine.Pin.IN, machine.Pin.PULL_UP)
        self.last_time_us = time.ticks_us()
        self.buffer = []
        self.MAX_PULSES = 100 # Max number of pulses/spaces to store
        self.last_code_hex = None # Stores the string of the last successfully decoded command
        self.last_code_time_ms = 0 # Timestamp of the last successfully decoded command
        self.repeat_delay_ms = 150 # Time within which a repeat code is expected after a command

        self.pin.irq(trigger=machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING, handler=self._ir_event_handler)
        self.new_data_available = False
        print(f"IR Receiver initialized on GPIO {pin_num}. Point remote and press buttons.")
        print("Look for 'IRQ:' messages for raw pulse data, and 'Decoding buffer:' for attempts.")

    def _ir_event_handler(self, pin_obj):
        current_time_us = time.ticks_us()
        pulse_duration = time.ticks_diff(current_time_us, self.last_time_us)
        self.last_time_us = current_time_us

        current_pin_value = self.pin.value() # State of the pin *after* the edge

        if pulse_duration < 100: # Ignore very short glitches
            return

        # Debug: Print raw pulse info
        # print(f"IRQ: {pulse_duration}us, Pin_now: {current_pin_value}, BufLen: {len(self.buffer)}")

        if len(self.buffer) >= self.MAX_PULSES:
            print("WARN: IR Buffer full. Clearing.")
            self.buffer.clear()
            return

        self.buffer.append(pulse_duration)

        # Heuristic for detecting end of message in IRQ
        # Condition 1: A long space has just ended (pin is now LOW), and we have a decent number of pulses
        if current_pin_value == 0 and pulse_duration > 30000 and len(self.buffer) > 30:
            # print(f"Debug: IRQ detected long space ({pulse_duration}us ended, pin now LOW), setting new_data_available.")
            self.new_data_available = True
        # Condition 2: Buffer is quite full, likely holding a complete NEC code
        elif len(self.buffer) > (2 + 32 * 2 + 1): # Header(2) + 32 bits (64) + stop bit (1) = 67 pulses
            # print(f"Debug: IRQ buffer has many pulses ({len(self.buffer)}), setting new_data_available.")
            self.new_data_available = True


    def _match(self, measured, expected):
        return (expected - TOLERANCE_US) <= measured <= (expected + TOLERANCE_US)

    def decode_nec(self):
        if not self.new_data_available:
            return None
        
        irq_state = machine.disable_irq()
        pulses = list(self.buffer)
        self.buffer.clear()
        self.new_data_available = False
        machine.enable_irq(irq_state)

        if not pulses:
            # print("Debug: Decode attempt on empty buffer.")
            return None

        # print(f"Decoding buffer (len {len(pulses)}): {pulses[:10]}...")

        if pulses[0] > INITIAL_IDLE_THRESHOLD_US:
            # print(f"Debug: Discarding initial long pulse: {pulses[0]}us")
            pulses.pop(0)
            if not pulses:
                # print("Debug: Buffer empty after discarding initial pulse.")
                return None
        
        try:
            if len(pulses) < 2:
                # print(f"Debug: Too few pulses for header after potential trim: {len(pulses)}")
                return None

            # Check for NEC Repeat Code first
            if self._match(pulses[0], NEC_HDR_MARK) and \
               len(pulses) >= 3 and \
               self._match(pulses[1], NEC_RPT_SPACE) and \
               self._match(pulses[2], NEC_BIT_MARK):
                current_time_ms = time.ticks_ms()
                if self.last_code_hex and \
                   time.ticks_diff(current_time_ms, self.last_code_time_ms) < self.repeat_delay_ms * 3: # Increased multiplier for repeat
                    self.last_code_time_ms = current_time_ms 
                    # print("Debug: Repeat code confirmed.")
                    return "REPEAT"
                # print(f"Debug: Repeat-like sequence, but no prior command or too late. Pulses: {pulses[0:3]}")
                return None 

            # Check for standard NEC Header
            if not self._match(pulses[0], NEC_HDR_MARK):
                # print(f"Debug: Header Mark mismatch: {pulses[0]} vs {NEC_HDR_MARK}. Buffer: {pulses[:5]}")
                return None

            if not self._match(pulses[1], NEC_HDR_SPACE):
                print(f"Debug: Header Space mismatch. Expected ~{NEC_HDR_SPACE}, got {pulses[1]}. Buffer context: {pulses[:5]}")
                return None
            
            # print("Debug: Header OK.")

            if len(pulses) < (2 + 32 * 2): # Need 2 header pulses + 32 bits * 2 pulses/bit = 66 pulses
                # print(f"Debug: Not enough pulses for 32 bits: {len(pulses)} (needed {2 + 32 * 2})")
                return None

            val = 0
            for i in range(32):
                mark_idx = 2 + i * 2
                space_idx = mark_idx + 1
                
                current_mark = pulses[mark_idx]
                current_space = pulses[space_idx]

                if not self._match(current_mark, NEC_BIT_MARK):
                    # print(f"Debug: Bit {i} Mark mismatch: {current_mark} vs {NEC_BIT_MARK}")
                    return None 

                val <<= 1
                if self._match(current_space, NEC_ONE_SPACE):
                    val |= 1
                elif self._match(current_space, NEC_ZERO_SPACE):
                    pass 
                else:
                    # print(f"Debug: Bit {i} Space mismatch: {current_space} (exp 0: {NEC_ZERO_SPACE}, exp 1: {NEC_ONE_SPACE})")
                    return None
            
            # print("Debug: 32 bits decoded.")
            
            # Optional: Check for stop bit mark after the 32nd bit's space
            # stop_bit_idx = 2 + 32 * 2
            # if len(pulses) > stop_bit_idx:
            #     if not self._match(pulses[stop_bit_idx], NEC_BIT_MARK):
            #         print(f"Debug: Stop bit mark mismatch: {pulses[stop_bit_idx]} vs {NEC_BIT_MARK} (often ignored)")
            # else:
            #     print("Debug: No pulse data for stop bit check.")

            addr = (val >> 24) & 0xFF
            not_addr = (val >> 16) & 0xFF
            cmd = (val >> 8) & 0xFF
            not_cmd = val & 0xFF

            if (cmd + not_cmd) != 0xFF: # Checksum for command part
                 # print(f"Debug: Command checksum error. Cmd: {cmd:02X}, NotCmd: {not_cmd:02X}")
                 pass # Be lenient with checksums for wider compatibility

            # Standard NEC also has addr + not_addr == 0xFF. Extended NEC doesn't always.
            # if (addr + not_addr) != 0xFF:
            #     print(f"Debug: Address checksum error. Addr: {addr:02X}, NotAddr: {not_addr:02X}")

            decoded_str = f"ADDR: {addr:02X}, CMD: {cmd:02X} (Full: {val:08X})"
            self.last_code_hex = decoded_str 
            self.last_code_time_ms = time.ticks_ms()
            return decoded_str

        except IndexError:
            # print(f"Debug: IndexError while decoding. Pulses available: {len(pulses)}")
            return None
        except Exception as e:
            # print(f"Debug: Exception during decode: {e}")
            return None

if __name__ == "__main__":
    ir = IRReceiver(IR_PIN_NUM)
    
    last_printed_code_time = 0 # Timestamp of the last *printed* code to console
    # DEBOUNCE_MS is for console print debouncing, not for repeat logic.
    # Repeat logic uses self.last_code_time_ms (time of last successful decode)
    CONSOLE_DEBOUNCE_MS = 300 

    while True:
        if ir.new_data_available:
            decoded_code = ir.decode_nec() 
            
            if decoded_code:
                current_time_ms = time.ticks_ms()
                # Debounce printing to console for rapidly repeated identical full codes
                # Repeats ("REPEAT") should always print if they are valid repeats of last_code_hex
                if decoded_code == "REPEAT":
                    print(f"Received: {decoded_code}")
                    # Update last_printed_code_time for repeats as well, to avoid flooding if REPEAT itself is sent too fast by faulty logic
                    last_printed_code_time = current_time_ms
                elif time.ticks_diff(current_time_ms, last_printed_code_time) > CONSOLE_DEBOUNCE_MS:
                    print(f"Received: {decoded_code}")
                    last_printed_code_time = current_time_ms
                # else:
                    # print(f"Debug: Decoded '{decoded_code}' but debounced for console print.")
            # else:
                # print("Debug: Main loop: decode_nec returned None.")
                # decode_nec itself prints debug info for failures

        # Fallback: if IRQ hasn't set new_data_available, check for long idle to trigger processing
        if not ir.new_data_available and len(ir.buffer) > 0:
            current_time_us = time.ticks_us()
            # If no new pulse for a while, and we have some data, try to decode
            if time.ticks_diff(current_time_us, ir.last_time_us) > 70000: # 70ms idle
                if len(ir.buffer) > 10: # Only if there's a decent amount of data
                    # print(f"Debug: Main loop timeout detected idle ({time.ticks_diff(current_time_us, ir.last_time_us)}us). Forcing decode attempt on buffer len {len(ir.buffer)}.")
                    ir.new_data_available = True

        time.sleep_ms(10)
