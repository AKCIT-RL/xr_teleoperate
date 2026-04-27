using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Unity.WebRTC;
using UnityEngine;
using WebSocketSharp;

public static class WebRTCUtils
{
    /// <summary>
    /// Recebe o SDP linha a linha e adiciona os candidates corretamente.
    /// </summary>
    /// <param name="peerConnection">O RTCPeerConnection da Unity</param>
    /// <param name="sdpLines">Lista de strings, cada uma representando uma linha do SDP</param>
    /// <param name="type">Tipo da SDP: "offer" ou "answer"</param>
    public static void ApplySDP(RTCPeerConnection peerConnection, List<string> sdpLines, string type)
    {
        if (peerConnection == null) throw new ArgumentNullException(nameof(peerConnection));
        if (sdpLines == null || sdpLines.Count == 0) throw new ArgumentException("SDP vazio", nameof(sdpLines));

        // Junta todas as linhas com \r\n
        string sdp = string.Join("\r\n", sdpLines) + "\r\n";

        // Cria RTCSessionDescription com o tipo correto
        RTCSdpType sdpType = type.ToLower() == "offer" ? RTCSdpType.Offer : RTCSdpType.Answer;
        RTCSessionDescription desc = new RTCSessionDescription
        {
            type = sdpType,
            sdp = sdp
        };

        try
        {
            // Aplica o SDP remoto
            peerConnection.SetRemoteDescription(ref desc);
            UnityEngine.Debug.Log($"SDP aplicado com sucesso ({type})!");
        }
        catch (Exception e)
        {
            UnityEngine.Debug.LogError($"Erro ao aplicar SDP: {e}");
        }
    }
}

public class WebRTCSignalingUnity : MonoBehaviour
{
    private RTCPeerConnection pc;
    private RTCDataChannel channel;
    private WebSocket ws;
    private VideoStreamTrack remoteVideoTrack;
    private Texture remoteVideoTexture;
    private volatile bool hasPendingVideoFrame;
    private int appliedVideoFrames = 0;
    private float lastVideoLogTime = 0f;

    [Header("Video Target")]
    public Renderer remoteVideoRenderer;

    [Header("Tracking")]
    public TrackerSender trackerSender;

    private bool gotAnswer = false;
    private RTCSessionDescription answerDesc;
    private Coroutine webRtcUpdateCoroutine;

    void Start()
    {
        WebRTC.Initialize();
        webRtcUpdateCoroutine = StartCoroutine(WebRTC.Update());
        StartCoroutine(WebRTCSetup());
    }

    void Update()
    {
        if (!hasPendingVideoFrame || remoteVideoTexture == null)
            return;

        ApplyRemoteTexture(remoteVideoTexture);
        appliedVideoFrames++;

        if (Time.unscaledTime - lastVideoLogTime > 1.0f)
        {
            Debug.Log($"🎞️ Remote video frames applied: {appliedVideoFrames}, texture: {remoteVideoTexture.width}x{remoteVideoTexture.height}");
            lastVideoLogTime = Time.unscaledTime;
        }

        hasPendingVideoFrame = false;
    }

    private void ApplyRemoteTexture(Texture texture)
    {
        // 3D renderer path (supports Built-in and URP shader property names)
        if (remoteVideoRenderer != null && remoteVideoRenderer.material != null)
        {
            var mat = remoteVideoRenderer.material;
            mat.mainTexture = texture;

            if (mat.HasProperty("_BaseMap"))
                mat.SetTexture("_BaseMap", texture);

            if (mat.HasProperty("_MainTex"))
                mat.SetTexture("_MainTex", texture);

            if (mat.HasProperty("_BaseColor"))
                mat.SetColor("_BaseColor", Color.white);

            if (mat.HasProperty("_Color"))
                mat.SetColor("_Color", Color.white);
        }
    }

    private IEnumerator SendTestMessages()
    {
        yield return new WaitForSeconds(0.1f); // dá um tempinho pro canal estabilizar
        channel.Send(System.Text.Encoding.UTF8.GetBytes("Oi do Unity!"));
        channel.Send(System.Text.Encoding.UTF8.GetBytes("Hello again!"));
    }

    private IEnumerator WaitAndSend()
    {
        while (channel.ReadyState != RTCDataChannelState.Open)
            yield return null;

        channel.Send("Oi do Unity!");
        channel.Send("Hello again!");
    }
    private IEnumerator WebRTCSetup()
    {
        // ----------------------------
        // 🌐 WEBSOCKET
        // ----------------------------
        //ws = new WebSocket("ws://192.168.1.20:8765");
        ws = new WebSocket("ws://192.168.1.20:8765");

        ws.OnOpen += (s, e) =>
        {
            Debug.Log("🌐 WebSocket conectado!");
            ws.Send("{\"client\":\"unity\"}");
        };

        ws.OnMessage += (s, e) =>
        {
            Debug.Log("📥 WS MSG: " + e.Data);
            HandleSignalingMessage(e.Data);
        };

        ws.Connect();

        // ----------------------------
        // 🔗 CONFIG DO RTC
        // ----------------------------
        var config = new RTCConfiguration
        {
            iceServers = new[]
            {
                new RTCIceServer
                {
                    urls = new[] { "stun:stun.l.google.com:19302" }
                }
            }
        };

        pc = new RTCPeerConnection(ref config);

        pc.OnConnectionStateChange = s =>
            Debug.Log("🔗 Connection State: " + s);

        pc.OnIceConnectionChange = state =>
        {
            Debug.Log("🧊 ICE State: " + state);

            if (state == RTCIceConnectionState.Connected)
            {
                Debug.Log("✅ ICE Connected, DataChannel should be open now!");

                if (channel.ReadyState == RTCDataChannelState.Open)
                {
                    channel.Send("Hello from Unity after ICE!");
                }
                else
                {
                    // Espera o canal abrir antes de enviar
                    StartCoroutine(WaitAndSend());
                }
            }
        };

        pc.OnIceCandidate = cand =>
        {
            if (cand == null)
            {
                ws.Send("{\"type\":\"candidate\",\"candidate\":null}");
                return;
            }

            if (string.IsNullOrEmpty(cand.Candidate))
                return;

            ws.Send(JsonUtility.ToJson(new IcePacket
            {
                type = "candidate",
                candidate = cand.Candidate,
                sdpMid = cand.SdpMid,
                sdpMLineIndex = cand.SdpMLineIndex
            }));
        };

        pc.OnTrack = e =>
        {
            if (e.Track is VideoStreamTrack video)
            {
                Debug.Log("🎥 Video track recebida do Python");
                remoteVideoTrack = video;
                remoteVideoTrack.OnVideoReceived += OnRemoteVideoReceived;
            }
        };

        // ----------------------------
        // 📡 DATA CHANNEL
        // ----------------------------
        channel = pc.CreateDataChannel("tracker");

        // Request remote video explicitly so the offer contains an m=video section.
        var videoTransceiverInit = new RTCRtpTransceiverInit
        {
            direction = RTCRtpTransceiverDirection.RecvOnly
        };
        pc.AddTransceiver(TrackKind.Video, videoTransceiverInit);

        channel.OnOpen = () =>
        {
            Debug.Log("🔥 UNITY: DataChannel OPEN");

            if (trackerSender != null)
            {
                trackerSender.SetChannel(channel);
                Debug.Log("✅ TrackerSender channel assigned on DataChannel open");
            }
            else
            {
                Debug.LogWarning("⚠️ TrackerSender is null on DataChannel open");
            }

            StartCoroutine(SendTestMessages());
        };

        channel.OnMessage = msg =>
        {
            Debug.Log("📥 Python → Unity: " + Encoding.UTF8.GetString(msg));
        };

        if (trackerSender == null)
            trackerSender = FindAnyObjectByType<TrackerSender>();

        if (trackerSender != null)
        {
            trackerSender.SetChannel(channel);
            Debug.Log("✅ TrackerSender found and channel pre-assigned");
        }
        else
        {
            Debug.LogWarning("⚠️ TrackerSender not found in scene. Pose packets will not be sent.");
        }

        // ----------------------------
        // 1️⃣ CRIAR OFFER
        // ----------------------------
        var op = pc.CreateOffer();
        yield return op;

        var offer = op.Desc;

        var opLocal = pc.SetLocalDescription(ref offer);
        yield return opLocal;

        while (ws.ReadyState != WebSocketState.Open)
        {
            Debug.Log("⏳ Aguardando WebSocket abrir...");
            yield return null;
        }

        Debug.Log("📤 WebSocket ABERTO, enviando Offer");
        Debug.Log("📤 Enviando para Python SDP:\n" + offer.sdp);

        ws.Send(JsonUtility.ToJson(new SdpPacket
        {
            type = "offer",
            sdp = offer.sdp
        }));

        // ----------------------------
        // 2️⃣ ESPERAR ANSWER DO PYTHON
        // ----------------------------
        while (!gotAnswer)
            yield return null;

    }

    private void OnRemoteVideoReceived(Texture texture)
    {
        remoteVideoTexture = texture;
        hasPendingVideoFrame = true;

        if (texture != null)
            Debug.Log($"🧩 OnRemoteVideoReceived: {texture.width}x{texture.height}");
    }

    // ==========================================================
    // PARSE DE MENSAGENS
    // ==========================================================
    private void HandleSignalingMessage(string msg)
    {
        if (msg.Contains("\"answer\""))
        {
            var p = JsonUtility.FromJson<SdpPacket>(msg);
            Debug.Log("🔥 Recebi ANSWER!");

            // Split SDP em linhas
            List<string> sdpLines = new List<string>(p.sdp.Split(new[] { "\r\n", "\n" }, StringSplitOptions.None));

            // Aplica SDP remoto e candidatos
            WebRTCUtils.ApplySDP(pc, sdpLines, "answer");

            gotAnswer = true;
            return;
        }

        if (msg.Contains("\"candidate\""))
        {
            var ice = JsonUtility.FromJson<IcePacket>(msg);

            if (string.IsNullOrEmpty(ice.candidate))
            {
                Debug.Log("🏁 ICE Python → Unity: fim dos candidates");
                pc.AddIceCandidate(null);
                return;
            }

            Debug.Log("🧊 ICE Python → Unity: " + ice.candidate);

            RTCIceCandidateInit tmp = new RTCIceCandidateInit
            {
                candidate = ice.candidate,
                sdpMid = ice.sdpMid,
                sdpMLineIndex = ice.sdpMLineIndex
            };

            var cand = new RTCIceCandidate(tmp);
            pc.AddIceCandidate(cand);
        }
    }

    private void OnDestroy()
    {
        if (remoteVideoTrack != null)
            remoteVideoTrack.OnVideoReceived -= OnRemoteVideoReceived;

        if (webRtcUpdateCoroutine != null)
            StopCoroutine(webRtcUpdateCoroutine);

        channel?.Close();
        pc?.Close();
        ws?.Close();
        WebRTC.Dispose();
    }
}

// ==========================================================
// PACKETS
// ==========================================================
[System.Serializable]
public class SdpPacket
{
    public string type;
    public string sdp;
}

[System.Serializable]
public class IcePacket
{
    public string type;
    public string candidate;
    public string sdpMid;
    public int? sdpMLineIndex;
}