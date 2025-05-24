# mpremote-Controllable NEC IR Sender for Raspberry Pi Pico
#
# Connections for a 3-pin IR Transmitter Module (VCC, GND, DATA):
# Module VCC -> 3.3V on Pico (e.g., Pin 36)
# Module GND -> GND on Pico (e.g., Pin 38)
# Module DATA -> GPIO Pin specified by IR_LED_PIN_NUM (e.g., GP16, Pin 21)
#
# This script can be controlled via mpremote in two ways:
# 1. As a script with arguments:
#    mpremote run ir_controller.py <HEXCODE> <REPEATS>
#    Example: mpremote run ir_controller.py 768910EF 0
#
# 2. By importing and calling a function from mpremote REPL:
#    mpremote repl
#    >>> import ir_controller
#    >>> ir_controller.send_ir("7689D02F", 1)
#    Or, as a one-liner:
#    mpremote repl --command "import ir_controller; ir_controller.send_ir('768910EF', 0)"

import machine
import time
import sys

# --- Configuration ---
IR_LED_PIN_NUM = 16  # GPIO pin connected to the IR transmitter module's DATA pin
CARRIER_FREQ_HZ = 38000  # Carrier frequency for NEC (typically 38kHz)
PWM_DUTY_CYCLE = 1 << 14 # 2**14 = 16384, approx 25% duty cycle for PWM (0-65535 range)

# --- NEC Protocol Timing Constants (in microseconds) ---
NEC_HDR_MARK_US = 9000
NEC_HDR_SPACE_US = 4500
NEC_BIT_MARK_US = 560
NEC_ONE_SPACE_US = 1690
NEC_ZERO_SPACE_US = 560
NEC_RPT_HDR_MARK_US = 9000
NEC_RPT_SPACE_US = 2250
NEC_RPT_BIT_MARK_US = 560
NEC_FRAME_GAP_MS = 40 # Minimum gap after a command or repeat

def _flush_stdout():
    """Helper function to flush stdout if available."""
    if hasattr(sys.stdout, 'flush'):
        sys.stdout.flush()

class IRSender:
    def __init__(self, pin_num, freq_hz, duty_cycle):
        self.pin = machine.Pin(pin_num, machine.Pin.OUT)
        self.pwm = machine.PWM(self.pin)
        self.pwm.freq(freq_hz)
        self.pwm.duty_u16(0) # Start with LED off
        self.carrier_freq_hz = freq_hz
        self.pwm_duty_on = duty_cycle
        self.pwm_duty_off = 0
        print(f"IR Sender initialized on GPIO {pin_num} at {freq_hz}Hz.", end='\r\n')
        _flush_stdout()

    def _mark(self, duration_us):
        self.pwm.duty_u16(self.pwm_duty_on)
        time.sleep_us(duration_us)
        self.pwm.duty_u16(self.pwm_duty_off)

    def _space(self, duration_us):
        self.pwm.duty_u16(self.pwm_duty_off)
        if duration_us > 0:
            time.sleep_us(duration_us)

    def _transmit_data(self, data_to_send_32bit, num_repeats=0):
        # Header
        self._mark(NEC_HDR_MARK_US)
        self._space(NEC_HDR_SPACE_US)
        # Data
        for i in range(32):
            bit = (data_to_send_32bit >> (31 - i)) & 1
            self._mark(NEC_BIT_MARK_US)
            if bit == 1:
                self._space(NEC_ONE_SPACE_US)
            else:
                self._space(NEC_ZERO_SPACE_US)
        # Stop Bit
        self._mark(NEC_BIT_MARK_US)
        self._space(0) 
        # Repeats
        for _ in range(num_repeats):
            time.sleep_ms(NEC_FRAME_GAP_MS)
            self._send_repeat_code()
            print("Sent REPEAT", end='\r\n')
            _flush_stdout()
        time.sleep_ms(NEC_FRAME_GAP_MS)

    def send_full_nec_hex(self, full_code_hex, num_repeats=0):
        if not (isinstance(full_code_hex, str) and len(full_code_hex) == 8):
            print(f"Error: Full hex code '{full_code_hex}' must be an 8-character string.", end='\r\n')
            _flush_stdout()
            return False
        try:
            data_to_send = int(full_code_hex, 16)
        except ValueError:
            print(f"Error: Invalid hexadecimal string '{full_code_hex}'.", end='\r\n')
            _flush_stdout()
            return False

        address = (data_to_send >> 24) & 0xFF
        not_address_check = (data_to_send >> 16) & 0xFF
        command = (data_to_send >> 8) & 0xFF
        not_command_check = data_to_send & 0xFF

        print(f"Sending NEC from full hex: '{full_code_hex}' with {num_repeats} repeat(s).", end='\r\n')
        if ((address ^ not_address_check) != 0xFF) or ((command ^ not_command_check) != 0xFF) :
             print(f"  Warning: Hex code 0x{full_code_hex} does not strictly follow standard NEC (Addr, ~Addr, Cmd, ~Cmd) format.", end='\r\n')
             print(f"  Interpreted parts: Addr=0x{address:02X}, AddrInv=0x{not_address_check:02X}, Cmd=0x{command:02X}, CmdInv=0x{not_command_check:02X}", end='\r\n')
        else:
             print(f"  Standard NEC format: Addr=0x{address:02X}, Cmd=0x{command:02X}", end='\r\n')
        _flush_stdout()

        self._transmit_data(data_to_send, num_repeats)
        print("Transmission sequence complete.", end='\r\n')
        _flush_stdout()
        return True

    def _send_repeat_code(self):
        self._mark(NEC_RPT_HDR_MARK_US)
        self._space(NEC_RPT_SPACE_US)
        self._mark(NEC_RPT_BIT_MARK_US)
        self._space(0)

    def deinit(self):
        self.pwm.deinit()
        print("IR Sender deinitialized.", end='\r\n')
        _flush_stdout()

# Global sender instance for the callable function, initialized on first use.
# This avoids re-initializing PWM for every call if used multiple times in a REPL session,
# but still allows for clean deinit.
_sender_instance = None

def send_ir(hex_code_str, num_repeats_int=0):
    """
    Initializes IR sender (if not already), sends an IR code, and deinitializes.
    Designed to be called from mpremote or other MicroPython scripts.
    """
    global _sender_instance
    success = False
    try:
        if _sender_instance is None:
            _sender_instance = IRSender(IR_LED_PIN_NUM, CARRIER_FREQ_HZ, PWM_DUTY_CYCLE)
        
        # Ensure num_repeats_int is an integer
        try:
            num_repeats = int(num_repeats_int)
            if num_repeats < 0:
                print("Error: Number of repeats cannot be negative. Setting to 0.", end='\r\n')
                _flush_stdout()
                num_repeats = 0
        except ValueError:
            print(f"Error: Invalid number of repeats '{num_repeats_int}'. Setting to 0.", end='\r\n')
            _flush_stdout()
            num_repeats = 0

        success = _sender_instance.send_full_nec_hex(hex_code_str, num_repeats)
    except Exception as e:
        print(f"An error occurred in send_ir: {e}", end='\r\n')
        _flush_stdout()
        # If an error occurs, try to deinitialize to clean up PWM
        if _sender_instance is not None:
            _sender_instance.deinit()
            _sender_instance = None # Reset instance
    # Note: We don't deinit here to allow multiple calls in a REPL session
    # without reinitializing PWM each time. A separate cleanup function could be added
    # or deinit could be called if the script is run with args.
    return success

def cleanup_ir_sender():
    """Deinitializes the global IR sender instance if it exists."""
    global _sender_instance
    if _sender_instance is not None:
        _sender_instance.deinit()
        _sender_instance = None
        print("Global IR sender cleaned up.", end='\r\n')
        _flush_stdout()
    else:
        print("No active global IR sender to clean up.", end='\r\n')
        _flush_stdout()


if __name__ == "__main__":
    print("--- mpremote IR Controller Script ---", end='\r\n')
    _flush_stdout()

    if len(sys.argv) >= 2 and sys.argv[1].upper() == "CLEANUP":
        cleanup_ir_sender()
    elif len(sys.argv) >= 3:
        # Called as: mpremote run ir_controller.py <HEXCODE> <REPEATS>
        # sys.argv[0] is script name
        hex_code = sys.argv[1].upper()
        repeats = 0
        if len(sys.argv) >= 4:
            try:
                repeats = int(sys.argv[2]) # Corrected index for repeats
                if repeats < 0:
                    print(f"Warning: Repeats '{sys.argv[2]}' cannot be negative. Setting to 0.", end='\r\n')
                    repeats = 0
            except ValueError:
                print(f"Warning: Invalid repeats value '{sys.argv[2]}'. Defaulting to 0.", end='\r\n')
                repeats = 0
        else: # Only hex code provided, repeats default to 0
             repeats = 0 # sys.argv[2] was for repeats, now it's sys.argv[3]
             # Corrected logic: if len(sys.argv) >= 3, hex_code is sys.argv[1], repeats is sys.argv[2]
             try:
                repeats = int(sys.argv[2])
                if repeats < 0:
                    print(f"Warning: Repeats '{sys.argv[2]}' cannot be negative. Setting to 0.", end='\r\n')
                    repeats = 0
             except ValueError:
                print(f"Warning: Invalid repeats value '{sys.argv[2]}'. Defaulting to 0.", end='\r\n')
                repeats = 0
             except IndexError: # Only hex code was provided
                print("Repeats not specified, defaulting to 0.", end='\r\n')
                repeats = 0


        print(f"Executing from command line: HEX={hex_code}, Repeats={repeats}", end='\r\n')
        _flush_stdout()
        
        # For command-line execution, create a temporary sender, use it, and deinit.
        temp_sender = IRSender(IR_LED_PIN_NUM, CARRIER_FREQ_HZ, PWM_DUTY_CYCLE)
        temp_sender.send_full_nec_hex(hex_code, repeats)
        temp_sender.deinit()
        print("Command line execution finished.", end='\r\n')

    else:
        print("Usage:", end='\r\n')
        print("  As a script: python this_script.py <HEXCODE> <REPEATS>", end='\r\n')
        print("  mpremote:    mpremote run this_script.py <HEXCODE> <REPEATS>", end='\r\n')
        print("               mpremote run this_script.py cleanup", end='\r\n')
        print("  Example:     mpremote run this_script.py 768910EF 0", end='\r\n')
        print("\nOr, import and use functions in mpremote REPL:", end='\r\n')
        print("  >>> import ir_controller  (or your script's filename without .py)", end='\r\n')
        print("  >>> ir_controller.send_ir('HEXCODE', REPEATS)", end='\r\n')
        print("  >>> ir_controller.cleanup_ir_sender() # Call when done with REPL session", end='\r\n')
        _flush_stdout()
    
    print("-----------------------------------", end='\r\n')
    _flush_stdout()


