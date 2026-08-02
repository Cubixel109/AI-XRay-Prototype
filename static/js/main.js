(function () {
  "use strict";


  // -----------------------------------------------------------
  // Fade-in animations
  // -----------------------------------------------------------

  const fadeTargets = document.querySelectorAll(".fade-in");


  if ("IntersectionObserver" in window && fadeTargets.length) {

    const observer = new IntersectionObserver(
      (entries) => {

        entries.forEach((entry) => {

          if (entry.isIntersecting) {

            entry.target.classList.add("is-visible");

            observer.unobserve(entry.target);

          }

        });

      },
      {
        threshold: 0.15,
        rootMargin: "0px 0px -40px 0px"
      }
    );


    fadeTargets.forEach((el) => observer.observe(el));

  } else {

    fadeTargets.forEach((el) =>
      el.classList.add("is-visible")
    );

  }



  // -----------------------------------------------------------
  // Elements
  // -----------------------------------------------------------

  const analyzeBtn = document.getElementById("analyzeBtn");
  const analyzeSpinner = document.getElementById("analyzeSpinner");
  const analyzeLabel = document.getElementById("analyzeLabel");

  const captureBtn = document.getElementById("captureBtn");
  const uploadBtn = document.getElementById("uploadBtn");
  const fileInput = document.getElementById("fileInput");

  const generateReportBtn = document.getElementById("generateReportBtn");
  const generateReportSpinner = document.getElementById("generateReportSpinner");
  const generateReportLabel = document.getElementById("generateReportLabel");

  const predictionValue = document.getElementById("predictionValue");
  const confidenceValue = document.getElementById("confidenceValue");
  const riskValue = document.getElementById("riskValue");
  const scanTimeValue = document.getElementById("scanTimeValue");
  const riskChip = document.getElementById("riskChip");
  const confidenceBarFill = document.getElementById("confidenceBarFill");

  const actionNote = document.getElementById("actionNote");
  const actionNoteDefaultText = actionNote ? actionNote.textContent : "";

  const ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png"];

 let cameraStream = null;

 const liveFeed = document.getElementById("liveFeed");
 const cameraCanvas = document.getElementById("cameraCanvas");


  // -----------------------------------------------------------
  // Shared busy-state + result-rendering helpers
  //
  // Both the Analyze flow (/analyze) and the Upload flow (/upload)
  // need to: (1) lock the action buttons while a request is in
  // flight, and (2) paint the exact same result fields once a
  // { status: "ok", prediction, confidence, risk, riskClass,
  // scanTime } response comes back. Centralizing that here means
  // there is only one place that touches the results DOM.
  // -----------------------------------------------------------

  function setBusy(isBusy) {

    if (captureBtn) captureBtn.disabled = isBusy;
    if (uploadBtn) uploadBtn.disabled = isBusy;

    if (analyzeBtn) analyzeBtn.disabled = isBusy;

    if (analyzeSpinner) analyzeSpinner.hidden = !isBusy;

    if (analyzeLabel) analyzeLabel.style.opacity = isBusy ? "0.5" : "1";

  }


  function renderAnalysisResult(result, elapsedSeconds) {

    const confidence = Number(result.confidence);


    if (predictionValue)
      predictionValue.textContent = result.prediction;


    if (confidenceValue)
      confidenceValue.textContent = confidence.toFixed(2) + "%";


    if (confidenceBarFill)
      confidenceBarFill.style.width = confidence + "%";


    if (riskValue)
      riskValue.textContent = result.risk;


    if (riskChip) {

      riskChip.textContent = result.risk + " Risk";

      riskChip.className = "chip chip--" + result.riskClass;

    }


    if (scanTimeValue) {

      scanTimeValue.textContent = elapsedSeconds.toFixed(2) + "s";

    }


    // A report can only ever be generated for an analysis that has
    // actually run, so the button stays disabled until we get here.
    if (generateReportBtn) generateReportBtn.disabled = false;

  }


  // -----------------------------------------------------------
  // Generate Report button busy-state helper (kept separate from
  // setBusy() above: downloading a report doesn't need to lock the
  // Capture/Upload/Analyze buttons, it only needs to lock itself).
  // -----------------------------------------------------------

  function setReportBusy(isBusy) {

    if (generateReportBtn) generateReportBtn.disabled = isBusy;

    if (generateReportSpinner) generateReportSpinner.hidden = !isBusy;

    if (generateReportLabel) generateReportLabel.style.opacity = isBusy ? "0.5" : "1";

  }


  function resetActionNote() {

    if (actionNote) actionNote.textContent = actionNoteDefaultText;

  }


  function showActionNote(message) {

    if (actionNote) actionNote.textContent = message;

  }

 // -----------------------------------------------------------
// Browser USB Camera
// -----------------------------------------------------------

async function startCamera() {

    try {

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: true
        });


        if (liveFeed) {

            liveFeed.srcObject = cameraStream;

        }


        console.log("Browser camera connected");


    } catch(error) {

        console.error(
            "Camera permission failed:",
            error
        );

        showActionNote(
    "No camera detected or permission denied. Upload an X-ray manually."
);

    }

}


startCamera();

  // -----------------------------------------------------------
  // AI Analysis
  // -----------------------------------------------------------

  async function runAIAnalysis() {


    if (!analyzeBtn || analyzeBtn.disabled)
      return;


    setBusy(true);


    const startTime = performance.now();



    try {


      const response = await fetch("/analyze", {

        method: "POST"

      });



      const result = await response.json();


      console.log(
        "AI Response:",
        result
      );



      if (result.status === "ok") {

        const elapsed = (performance.now() - startTime) / 1000;

        renderAnalysisResult(result, elapsed);

      }

      else {


        console.error(
          "Backend error:",
          result.message
        );


        alert(
          "Analysis failed: " +
          result.message
        );


      }



    }

    catch (error) {


      console.error(
        "Connection error:",
        error
      );


      alert(
        "AI analysis failed."
      );


    }



    setBusy(false);


  }




  if (analyzeBtn) {

    analyzeBtn.addEventListener(
      "click",
      runAIAnalysis
    );

  }


  // -----------------------------------------------------------
  // Generate Report
  //
  // Calls /generate_report, which builds a PDF from whichever
  // analysis result is currently cached server-side, and triggers
  // an automatic browser download -- no separate "view" step.
  // -----------------------------------------------------------

  async function generateReport() {

    if (!generateReportBtn || generateReportBtn.disabled)
      return;

    setReportBusy(true);

    try {

      const response = await fetch("/generate_report", {
        method: "POST"
      });

      if (!response.ok) {

        const errorBody = await response.json().catch(() => null);

        const message =
          errorBody && errorBody.message
            ? errorBody.message
            : "Report generation failed.";

        alert(message);

        setReportBusy(false);
        return;

      }

      const blob = await response.blob();

      // The backend already picked a filename like
      // "ScanSense_Report_SS-20260802-001.pdf" -- read it out of
      // the Content-Disposition header instead of guessing one
      // here, so the two never drift apart.
      const disposition = response.headers.get("Content-Disposition") || "";
      const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
      const filename = filenameMatch ? filenameMatch[1] : "ScanSense_Report.pdf";

      const downloadUrl = window.URL.createObjectURL(blob);

      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();

      window.URL.revokeObjectURL(downloadUrl);

      showActionNote("Report downloaded: " + filename);

    }

    catch (error) {

      console.error(
        "Report generation error:",
        error
      );

      alert(
        "Report generation failed."
      );

    }

    setReportBusy(false);

  }


  if (generateReportBtn) {

    generateReportBtn.addEventListener(
      "click",
      generateReport
    );

  }



// -----------------------------------------------------------
// Capture Button
// -----------------------------------------------------------

if (captureBtn) {


captureBtn.addEventListener(
"click",
async()=>{


if(!liveFeed || !cameraCanvas){

    alert("Camera not available");
    return;

}


cameraCanvas.width = liveFeed.videoWidth;
cameraCanvas.height = liveFeed.videoHeight;


const ctx = cameraCanvas.getContext("2d");


ctx.drawImage(
    liveFeed,
    0,
    0,
    cameraCanvas.width,
    cameraCanvas.height
);



cameraCanvas.toBlob(
async(blob)=>{


let formData = new FormData();


formData.append(
    "image",
    blob,
    "camera_capture.jpg"
);



try {


const response = await fetch(
    "/upload",
    {
        method:"POST",
        body:formData
    }
);



const result = await response.json();



console.log(
    "Camera capture:",
    result
);



if(result.status==="ok"){

    renderAnalysisResult(
        result,
        Number(result.scanTime.replace("s",""))
    );

    showActionNote(
        "Camera image analyzed successfully"
    );

}

else{

    alert(
        result.message
    );

}



}

catch(error){

console.error(error);

alert(
"Camera upload failed"
);

}



},
"image/jpeg"
);



}
);


}

 
  // -----------------------------------------------------------
  // Upload Button
  //
  // Opens the file picker, uploads the chosen JPG/PNG to /upload,
  // and renders the result with the SAME renderAnalysisResult()
  // helper the Analyze button uses -- /upload already runs the
  // AI analysis server-side and returns the identical response
  // shape as /analyze, so there is no separate prediction logic
  // here at all.
  // -----------------------------------------------------------

  function fileExtension(filename) {

    const parts = filename.split(".");

    return parts.length > 1 ? parts.pop().toLowerCase() : "";

  }


  if (uploadBtn && fileInput) {

    uploadBtn.addEventListener("click", () => {

      fileInput.click();

    });


    fileInput.addEventListener("change", async (event) => {

      const file = event.target.files && event.target.files[0];

      if (!file) return;


      const ext = fileExtension(file.name);

      if (!ALLOWED_EXTENSIONS.includes(ext)) {

        alert("Please choose a .jpg, .jpeg, or .png image.");

        fileInput.value = "";

        return;

      }


      setBusy(true);

      showActionNote("Uploading " + file.name + "...");


      const startTime = performance.now();


      try {

        const formData = new FormData();

        formData.append("image", file);


        const response = await fetch("/upload", {

          method: "POST",

          body: formData

        });


        const result = await response.json();


        console.log(
          "Upload:",
          result
        );


        if (result.status === "ok") {

          const elapsed = (performance.now() - startTime) / 1000;

          renderAnalysisResult(result, elapsed);

          showActionNote("Analyzed uploaded image: " + file.name);

        }

        else {

          console.error(
            "Backend error:",
            result.message
          );

          alert(
            "Upload failed: " +
            result.message
          );

          resetActionNote();

        }


      }

      catch (error) {

        console.error(
          error
        );

        alert(
          "Image upload failed."
        );

        resetActionNote();

      }


      setBusy(false);

      fileInput.value = "";


    });

  }



})();