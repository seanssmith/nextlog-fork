import logging
import requests
import threading
import redis
import time
import json
import datetime


class Logger(logging.Logger):
    def __init__(self,*args,**kwargs):
        super().__init__(*args)

        self.loki_url = kwargs.get('loki_url',None)
        self.labels = kwargs.get('labels',{})
        self.redis_server = redis.Redis(host='localhost',port=6379,db=0)
        # Replace the running flag with threading.Event
        self.stop_event = threading.Event()
        
        # Initialize and start the send_logs_thread
        self.send_logs_thread = threading.Thread(target=self.send_logs)
        self.send_logs_thread.start()

    def send_logs(self):
        while not self.stop_event.is_set():
            time.sleep(1) 
            if self.loki_url:
                log_entry = self.redis_server.lindex('log_queue',1)
                if log_entry:
                    try:
                        response = self.api_call_loki(log_entry)
                        self.redis_server.lpop('log_queue')
                    except requests.exceptions.RequestException as e:
                        self.error(f"Failed to send logs: {e}") # Send error log to logger
                        break
                else:
                    pass

    def api_call_loki(self, redis_log_entry):

        log_entry = redis_log_entry.decode("utf-8").replace("'", '"')
        log_entry_json = json.loads(log_entry)

        payload = {
            "streams": [
                {
                    "labels": self.get_labels_string(self.labels),
                    "entries": [
                        {
                            "ts" : log_entry_json['timestamp'],
                            "line": f"[{log_entry_json['level']}] {log_entry_json['line']}"
                        }
                    ]            
                }

            ]
        }

        headers = {
            'Content-type': 'application/json'
        }

        payload = json.dumps(payload)
        
        response = requests.post(self.loki_url,data=payload,headers=headers)
        return response
    
    def get_labels_string(self,labels_map):
        labels_string = "{"
        for key, value in labels_map.items():
            labels_string += f"{key}=\"{value}\", "
        # Remove the trailing comma and space
        labels_string = labels_string.rstrip(", ")
        labels_string += "}"
        return labels_string



    def info(self,msg):
        self.push_to_redis(msg,"INFO")
        super().info(msg)
    
    def debug(self,msg):
        self.push_to_redis(msg,"DEBUG")
        super().debug(msg)
    
    def warning(self,msg):
        self.push_to_redis(msg,"WARNING")
        super().warning(msg)
    
    def error(self,msg):
        self.push_to_redis(msg,"ERROR")
        super().error(msg)
   
    def critical(self,msg):
        self.push_to_redis(msg,"CRITICAL")
        super().critical(msg)
    
    def push_to_redis(self,msg,log_level):
        timestamp = datetime.datetime.utcnow()
        timestampstr = timestamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.redis_server.rpush('log_queue',str({"level":log_level,"timestamp": timestampstr,'line':msg}))

    def stop(self):
        self.stop_event.set()  # Signal the thread to stop
        self.info("Logger: Waiting for logs to finish sending...")
        self.send_logs_thread.join()  # Wait for the thread to finish
        time.sleep(5) # Wait for 5 seconds because for some reason some logs take a few seconds