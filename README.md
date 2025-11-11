# DataPulse

Python-Based Modbus TCP Monitoring & Logging Tool with Tkinter GUI

DataPulse is a Python project designed to establish, monitor, and log Modbus TCP communication between a client and server.
The application provides a user-friendly Tkinter GUI with dual language support (English and Turkish), dark/light mode themes, and database logging with timestamps for reviewing past readings.
Due to the lack of a real industrial device, the project was thoroughly tested using Modbus simulator tools such as EasyModbus TCP. (https://github.com/rossmann-engineering/EasyModbusTCP.NET)

🔹 Features

Real-time reading and writing of Modbus registers

Tkinter GUI with Dark/Light mode support

Dual language interface: English & Turkish

Database logging: stores all read/write operations with timestamps for review

Connection status and error management in real time

Learning, demonstration, and testing purposes

Cross-platform: Windows, Linux, macOS


🖥️ GUI Overview

Enter target IP, port, and register addresses

Read or write values to Modbus registers

Monitor connection status and error messages in real time

Switch between Dark and Light mode

Switch languages between English and Turkish

View logged operations with timestamps

Tip: When using simulator tools, ensure that the IP and port match the simulator settings.

📝 Notes

This project is primarily educational and demonstrational

Although tested with Modbus simulators, it is compatible with any device supporting Modbus TCP

The Tkinter GUI allows users with minimal Python experience to interact easily

Database logging provides an easy way to track and review past operations, which is useful for testing and analysis

⚡ Technologies Used

Python 3.x

Tkinter (GUI, Dark/Light mode)

Pymodbus (Modbus TCP communication)

SQLite3 (Database logging with timestamps)

Tested with EasyModbus TCP simulator

📄 License

MIT License © 2025 Alperen
