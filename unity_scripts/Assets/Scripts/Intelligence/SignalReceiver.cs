using System;
using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;
using UnityEngine.Events;

namespace Kelompok2.Intelligence
{
    /// <summary>
    /// Penerima paket JSON UDP lintas proses dengan pemantauan detak jantung (watchdog).
    /// </summary>
    public class SignalReceiver : MonoBehaviour
    {
        [Header("Konfigurasi Jaringan Lokal")]
        [SerializeField] private int listenPort = 5055;
        [SerializeField] private float heartbeatTimeoutSeconds = 2.5f;

        [Header("Status Koneksi (Read-Only)")]
        [SerializeField] private bool isLinkAlive;
        [SerializeField] private int lastSequenceNumber;
        [SerializeField] private float secondsSinceLastPacket;

        public UnityEvent<SignalPacket> onPacketReceived;
        public UnityEvent<bool> onLinkStatusChanged;

        public bool IsLinkAlive => isLinkAlive;
        public int LastSequenceNumber => lastSequenceNumber;

        private UdpClient _udpClient;
        private Thread _receiveThread;
        private volatile bool _isRunning;
        private readonly ConcurrentQueue<SignalPacket> _packetQueue = new ConcurrentQueue<SignalPacket>();
        private float _lastPacketUnityTime = -999f;
        private bool _hasReceivedAnyPacket;

        private void OnEnable()
        {
            StartListening();
        }

        private void OnDisable()
        {
            StopListening();
        }

        private void OnDestroy()
        {
            StopListening();
        }

        private void Update()
        {
            while (_packetQueue.TryDequeue(out SignalPacket packet))
            {
                if (packet.seq > 0 && packet.seq <= lastSequenceNumber)
                {
                    // Abaikan paket kedaluwarsa jika datang tidak berurutan
                    continue;
                }

                lastSequenceNumber = packet.seq;
                _lastPacketUnityTime = Time.unscaledTime;
                _hasReceivedAnyPacket = true;

                if (!isLinkAlive)
                {
                    SetLinkAlive(true);
                }

                onPacketReceived?.Invoke(packet);
            }

            if (_hasReceivedAnyPacket)
            {
                secondsSinceLastPacket = Time.unscaledTime - _lastPacketUnityTime;
                if (isLinkAlive && secondsSinceLastPacket > heartbeatTimeoutSeconds)
                {
                    SetLinkAlive(false);
                }
            }
        }

        public void StartListening()
        {
            if (_isRunning)
            {
                return;
            }

            try
            {
                _udpClient = new UdpClient(listenPort);
                _udpClient.Client.ReceiveTimeout = 500;
                _isRunning = true;

                _receiveThread = new Thread(ReceiveLoop)
                {
                    IsBackground = true,
                    Name = "SignalReceiverThread"
                };
                _receiveThread.Start();
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SignalReceiver] Gagal membuka port UDP {listenPort}: {ex.Message}");
                _isRunning = false;
            }
        }

        public void StopListening()
        {
            _isRunning = false;

            if (_udpClient != null)
            {
                try
                {
                    _udpClient.Close();
                }
                catch (Exception)
                {
                    // Abaikan galat saat menutup soket
                }
                _udpClient = null;
            }

            if (_receiveThread != null && _receiveThread.IsAlive)
            {
                _receiveThread.Join(300);
                _receiveThread = null;
            }
        }

        private void ReceiveLoop()
        {
            IPEndPoint remoteEndpoint = new IPEndPoint(IPAddress.Any, 0);

            while (_isRunning)
            {
                try
                {
                    byte[] data = _udpClient.Receive(ref remoteEndpoint);
                    string json = Encoding.UTF8.GetString(data);
                    SignalPacket packet = JsonUtility.FromJson<SignalPacket>(json);
                    if (packet != null)
                    {
                        _packetQueue.Enqueue(packet);
                    }
                }
                catch (SocketException)
                {
                    // Timeout periodik agar thread bisa memeriksa flag _isRunning
                }
                catch (ObjectDisposedException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    if (_isRunning)
                    {
                        Debug.LogWarning($"[SignalReceiver] Paket tidak valid diabaikan: {ex.Message}");
                    }
                }
            }
        }

        private void SetLinkAlive(bool alive)
        {
            isLinkAlive = alive;
            onLinkStatusChanged?.Invoke(alive);
        }
    }
}
