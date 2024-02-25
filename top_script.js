var coll = document.getElementsByClassName("collbutton");
var j;

function startUp() {
for (j = 0; j < coll.length; j++) {
    var contentR = coll[j].nextElementSibling;  
    if (contentR.classList.contains("inactive_content")) {
        contentR.style.maxHeight = 0;
    } else {
      contentR.style.maxHeight = contentR.scrollHeight + "px";
    };
    };
};
