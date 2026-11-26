using System;

namespace Kelompok2.Intelligence
{
    /// <summary>
    /// Kontrak data netral yang diterima dari proses penghasil data eksternal.
    /// </summary>
    [Serializable]
    public class SignalPacket
    {
        public int seq;
        public double timestamp;
        public string token;
        public string utterance;
        public float confidence;
        public float margin;
        public float signal_level;
        public float signal_to_noise_db;
        public bool is_active;
        public bool heartbeat;
    }

    /// <summary>
    /// Maksud perintah konstruksi hasil pemetaan token netral di lapis pemakai.
    /// </summary>
    public enum ConstructionIntent
    {
        None = 0,
        RaiseMaterial = 1,   // CMD_1: ANGKAT
        LowerMaterial = 2,   // CMD_2: TURUN
        EmergencyHold = 3,   // CMD_3: TAHAN
        CancelAction = 4,    // CMD_4: BATAL
        ConfirmAction = 5    // CMD_5: KONFIRMASI
    }

    /// <summary>
    /// Status keputusan sistem kecerdasan saat mengevaluasi masukan tidak pasti.
    /// </summary>
    public enum DecisionState
    {
        Idle = 0,
        Executed = 1,
        NeedsConfirmation = 2,
        HeldBack = 3,
        SafetyBlocked = 4,
        LinkDisconnected = 5
    }

    /// <summary>
    /// Ringkasan hasil evaluasi yang diteruskan ke antarmuka dan supervisor adegan.
    /// </summary>
    [Serializable]
    public struct EvaluatedDecision
    {
        public ConstructionIntent intent;
        public DecisionState state;
        public float confidence;
        public float margin;
        public float snrDb;
        public bool fromFallback;
        public string reason;
    }
}
