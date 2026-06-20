import sys
import os
import traceback

# カレントディレクトリをスクリプトの親ディレクトリに設定
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

try:
    import src.app
    src.app.main()
except Exception as e:
    log_path = os.path.join(script_dir, "app_error.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("=== Application Startup Error ===\n")
        traceback.print_exc(file=f)
    print("Error during startup. Check app_error.log for details.")
    sys.exit(1)
